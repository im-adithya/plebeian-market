import bleach
import btc2fiat
from datetime import datetime, timedelta
import ecdsa
from ecdsa.keys import BadSignatureError
from email_validator import validate_email, EmailNotValidError
from flask import Blueprint, jsonify, redirect, request
from io import BytesIO
import jwt
import lnurl
import os
import pyqrcode
import secrets
from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
import time

from extensions import db
import models as m
from main import app, get_lnd_client, get_nostr, get_s3, get_twitter
from main import get_token_from_request, get_user_from_token, user_required
from main import MempoolSpaceError
from utils import usd2sats, parse_xpub, UnknownKeyTypeError

api_blueprint = Blueprint('api', __name__)

@api_blueprint.route('/api/healthcheck', methods=['GET'])
def healthcheck(): # TODO: I don't really like this, for some reason, but it is used in "dev" mode by docker-compose
    return jsonify({'success': True})

# PUT would make more sense than GET, but the lightning wallets only do GET - perhaps we could split this in two parts - the part called by our app and the GET done by the wallet
@api_blueprint.route('/api/login', methods=['GET'], defaults={'deprecated': True}) # deprecated, but still used by the WP plugin
@api_blueprint.route('/api/login/lnurl', methods=['GET'], defaults={'deprecated': False})
def login_lnurl(deprecated):
    if deprecated:
        return redirect(f"{app.config['BASE_URL']}/api/login/lnurl", code=301)

    if 'k1' not in request.args:
        # first request to /login => we return a challenge (k1) and a QR code
        k1 = secrets.token_hex(32)

        db.session.add(m.LnAuth(k1=k1))
        db.session.commit()

        url = app.config['BASE_URL'] + f"/api/login?tag=login&k1={k1}"
        ln_url = lnurl.encode(url).bech32
        qr = BytesIO()
        pyqrcode.create(ln_url).svg(qr, omithw=True, scale=4)

        return jsonify({'k1': k1, 'lnurl': str(ln_url), 'qr': qr.getvalue().decode('utf-8')})

    lnauth = m.LnAuth.query.filter_by(k1=request.args['k1']).first()

    if not lnauth:
        return jsonify({'message': "Verification failed."}), 400

    if lnauth.created_at < datetime.utcnow() - timedelta(minutes=m.LnAuth.EXPIRE_MINUTES):
        return jsonify({'message': "Login token expired."}), 410

    if 'key' in request.args and 'sig' in request.args:
        # request made by the Lightning wallet, includes a key and a signature

        if lnauth.key and request.args['key'] != lnauth.key:
            # lnauth should not have a "key" here, unless the user scanned the QR code already
            # but then the key in the request should match the key we saved on the previous scan
            app.logger.warning(f"Dubious request with a key {request.args['key']} different from the existing key for k1 {lnauth.k1}.")
            return jsonify({'message': "Verification failed."}), 400
        if not lnauth.key:
            try:
                k1_bytes, key_bytes, sig_bytes = map(lambda k: bytes.fromhex(request.args[k]), ['k1', 'key', 'sig'])
            except ValueError:
                return jsonify({'message': "Invalid parameter."}), 400

            vk = ecdsa.VerifyingKey.from_string(key_bytes, curve=ecdsa.SECP256k1)
            try:
                vk.verify_digest(sig_bytes, k1_bytes, sigdecode=ecdsa.util.sigdecode_der)
            except BadSignatureError:
                return jsonify({'message': "Verification failed."}), 400

            lnauth.key = request.args['key']

            db.session.commit()

        return jsonify({})

    if not lnauth.key:
        # this is the browser continuously checking whether log in happened by passing in the challenge (k1)
        return jsonify({'success': False})

    user = m.User.query.filter_by(lnauth_key=lnauth.key).first()

    if not user:
        user = m.User(lnauth_key=lnauth.key)
        db.session.add(user)

    db.session.delete(lnauth)
    db.session.commit()

    token = jwt.encode({'user_lnauth_key': user.lnauth_key, 'exp': datetime.utcnow() + timedelta(days=app.config['JWT_EXPIRE_DAYS'])}, app.config['SECRET_KEY'], "HS256")

    return jsonify({'success': True, 'token': token, 'user': user.to_dict(for_user=user.id)})

@api_blueprint.route('/api/login/nostr', methods=['PUT'])
def login_nostr():
    if 'npub' not in request.json:
        return jsonify({'message': "Missing npub."}), 400

    if 'verification_phrase' not in request.json:
        existing_auth = m.NostrAuth.query.filter_by(key=request.json['npub']).first()
        if existing_auth:
            db.session.delete(existing_auth)
            db.session.commit()
        auth = m.NostrAuth(key=request.json['npub'])
        auth.generate_verification_phrase()
        get_nostr().send_dm(user_npub=auth.key, body=auth.verification_phrase)
        db.session.add(auth)
        db.session.commit()

        return jsonify({})
    else:
        auth = m.NostrAuth.query.filter_by(key=request.json['npub']).first()
        if not auth:
            return jsonify({'message': "Verification failed."}), 400
        if not auth.verification_phrase == request.json['verification_phrase']:
            return jsonify({'message': "Verification failed.", 'invalid_verification_phrase': True}), 400

        user = m.User.query.filter_by(nostr_public_key=auth.key).first()

        if not user:
            user = m.User(nostr_public_key=auth.key)
            db.session.add(user)

        db.session.delete(auth)
        db.session.commit()

        token = jwt.encode({'user_nostr_public_key': user.nostr_public_key, 'exp': datetime.utcnow() + timedelta(days=app.config['JWT_EXPIRE_DAYS'])}, app.config['SECRET_KEY'], "HS256")

        return jsonify({'success': True, 'token': token, 'user': user.to_dict(for_user=user.id)})

@api_blueprint.route('/api/users/<nym>', methods=['GET'])
def get_profile(nym):
    requesting_user = get_user_from_token(get_token_from_request())
    for_user_id = requesting_user.id if requesting_user else None
    user = m.User.query.filter_by(nym=nym).first()
    if not user:
        return jsonify({'message': "User not found"}), 404
    return jsonify({'user': user.to_dict(for_user=for_user_id)})

@api_blueprint.route('/api/users/me', methods=['GET'])
@user_required
def get_me(user):
    return jsonify({'user': user.to_dict(for_user=user.id)})

@api_blueprint.route('/api/users/me', methods=['PUT'])
@user_required
def put_me(user):
    if 'nym' in request.json:
        clean_nym = (request.json['nym'] or "").lower().strip()
        if clean_nym != user.nym:
            if len(clean_nym) < 3:
                return jsonify({'message': "Your nym needs to be at least 3 characters long!"}), 400
            if not clean_nym.isalnum():
                return jsonify({'message': "Your nym can only contain letters and numbers!"}), 400
            if m.User.query.filter_by(nym=clean_nym).one_or_none():
                return jsonify({'message': "Your nym is already in use!", 'field': 'nym', 'reason': 'duplicated'}), 400
            user.nym = clean_nym

    if 'email' in request.json:
        clean_email = (request.json['email'] or "").lower().strip()
        try:
            clean_email = validate_email(clean_email).email
        except EmailNotValidError:
            return jsonify({'message': "Your email address is not valid."}), 400
        if clean_email != user.email:
            if m.User.query.filter_by(email=clean_email).one_or_none():
                return jsonify({'message': "Somebody already registered this email address!"}), 400
            user.email = clean_email
            user.email_verified = False

    if 'telegram_username' in request.json:
        clean_username = (request.json['telegram_username'] or "").lower().strip()
        if clean_username.startswith("@"):
            clean_username = clean_username.removeprefix("@")
        if clean_username != user.telegram_username:
            if len(clean_username) < 3:
                return jsonify({'message': "Your Telegram username needs to be at least 3 characters long!"}), 400
            if not clean_username.replace("_", "").isalnum():
                return jsonify({'message': "Your Telegram username can only contain letters, numbers and underscores!"}), 400
            if m.User.query.filter_by(telegram_username=clean_username).one_or_none():
                return jsonify({'message': "Somebody already registered this Telegram username!"}), 400
            user.telegram_username = clean_username
            user.telegram_username_verified = False

    if 'twitter_username' in request.json:
        clean_username = (request.json['twitter_username'] or "").lower().strip()
        if clean_username.startswith("@"):
            clean_username = clean_username.removeprefix("@")
        if clean_username != user.twitter_username:
            if len(clean_username) < 3:
                return jsonify({'message': "Your Twitter username needs to be at least 3 characters long!"}), 400
            if not clean_username.replace("_", "").isalnum():
                return jsonify({'message': "Your Twitter username can only contain letters, numbers and underscores!"}), 400
            if m.User.query.filter_by(twitter_username=clean_username).one_or_none():
                return jsonify({'message': "Somebody already registered this Twitter username!"}), 400
            if user.nym == user.twitter_username:
                # NB: if the user has set a custom nym, don't overwrite that!
                user.nym = clean_username

            user.twitter_username = clean_username
            user.twitter_username_verified = False
            user.generate_twitter_verification_phrase()

            twitter = get_twitter()
            twitter_user = twitter.get_user(user.twitter_username)
            if not twitter_user:
                return jsonify({'message': "Twitter profile not found!"}), 400

            if app.config['ENV'] == 'prod':
                if user.twitter_username not in app.config['TWITTER_USER_MIN_AGE_DAYS_WHITELIST']:
                    if twitter_user['created_at'] > (datetime.utcnow() - timedelta(days=app.config['TWITTER_USER_MIN_AGE_DAYS'])):
                        return jsonify({'message': f"Twitter profile needs to be at least {app.config['TWITTER_USER_MIN_AGE_DAYS']} days old!"}), 400

            if not user.fetch_twitter_profile_image(twitter_user['profile_image_url'], get_s3()):
                return jsonify({'message': "Error fetching profile picture!"}), 400

            if not user.fetch_twitter_profile_banner(twitter_user['profile_banner_url'], get_s3()):
                return jsonify({'message': "Error fetching profile banner!"}), 400

            twitter.send_dm(twitter_user['id'], user.twitter_verification_phrase)
            user.twitter_verification_phrase_sent_at = datetime.utcnow()

    if 'contribution_percent' in request.json:
        user.contribution_percent = request.json['contribution_percent']

    if 'xpub' in request.json:
        try:
            k = parse_xpub(request.json['xpub'])
        except UnknownKeyTypeError as e:
            return jsonify({'message': "Invalid XPUB."}), 400
        try:
            first_address = k.subkey(0).subkey(0).address()
        except AttributeError:
            return jsonify({'message': "Invalid XPUB."}), 400
        user.xpub = request.json['xpub']
        user.xpub_index = 0

    if 'stall_name' in request.json:
        user.stall_name = bleach.clean(request.json['stall_name'])

    if 'stall_description' in request.json:
        user.stall_description = bleach.clean(request.json['stall_description'])

    if 'nostr_private_key' in request.json:
        user.nostr_private_key = request.json['nostr_private_key']

    try:
        db.session.commit()
    except IntegrityError:
        app.logger.exception(f"Error while saving user profile. {user.id=}")

        # there are very few cases where this could happen
        # namely with some old users that were created before we started saving the "clean" version of nym / twitter in the DB
        return jsonify({'message': "Please retry or contact support!"}), 500

    return jsonify({'user': user.to_dict(for_user=user.id)})

@api_blueprint.route('/api/users/me/verify/twitter', methods=['PUT'])
@user_required
def verify_twitter(user):
    if request.json.get('resend'):
        if user.twitter_verification_phrase_sent_at and user.twitter_verification_phrase_sent_at >= datetime.utcnow() - timedelta(minutes=1):
            return jsonify({'message': "Please wait at least one minuted before requesting a new verification phrase!"}), 400
        user.generate_twitter_verification_phrase()
        twitter = get_twitter()
        twitter_user = twitter.get_user(user.twitter_username)
        if not twitter_user:
            return jsonify({'message': "Twitter user not found!"}), 500
        if not twitter.send_dm(twitter_user['id'], user.twitter_verification_phrase):
            return jsonify({'message': f"Please allow DMs from @{app.config['TWITTER_USER']}"}), 400
        user.twitter_verification_phrase_sent_at = datetime.utcnow()
        db.session.commit()
        return jsonify({})

    if not request.json.get('phrase'):
        return jsonify({'message': "Please provide the verification phrase!"}), 400

    if user.twitter_verification_phrase_check_counter > 5:
        return jsonify({'message': "Please try requesting a new verification phrase!"}), 400

    clean_phrase = ' '.join([w for w in request.json['phrase'].lower().split(' ') if w])

    if get_twitter().get_verification_phrase(user) == clean_phrase:
        user.twitter_username_verified = True
        db.session.commit()
        return jsonify({})
    else:
        time.sleep(2 ** user.twitter_verification_phrase_check_counter)
        user.twitter_verification_phrase_check_counter += 1
        db.session.commit()
        return jsonify({'message': "Invalid verification phrase."}), 400

@api_blueprint.route('/api/users/me/notifications', methods=['GET', 'PUT'])
@user_required
def user_notifications(user):
    existing_notifications = {
        n.notification_type: n for n in m.UserNotification.query.filter_by(user_id=user.id).all()
    }
    if request.method == 'GET':
        notifications = []
        for t in m.NOTIFICATION_TYPES:
            if t in existing_notifications:
                notifications.append((False, existing_notifications[t]))
            else:
                notifications.append((True, m.UserNotification(notification_type=t, action=m.NOTIFICATION_TYPES[t].default_action)))
        return jsonify({'notifications': [n.to_dict() | {'is_default': is_default} for (is_default, n) in notifications]})
    elif request.method == 'PUT':
        for notification in request.json['notifications']:
            if notification['notification_type'] not in existing_notifications:
                db.session.add(m.UserNotification(
                    user_id=user.id,
                    notification_type=notification['notification_type'],
                    action=notification['action']))
            else:
                existing_notifications[notification['notification_type']].action = notification['action']
        db.session.commit()
        return jsonify({})

@api_blueprint.route('/api/users/me/resume', methods=['GET', 'PUT'])
@user_required
def user_resume(user):
    if request.method == 'GET':
        return jsonify({
            'job_title': user.resume_job_title,
            'bio': user.resume_bio,
            'desired_salary_usd': user.resume_desired_salary_usd,
            'bitcoiner_question': user.resume_bitcoiner_question,
            'skills': [s.to_dict() for s in user.resume_skills],
            'portfolio': [p.to_dict() for p in user.resume_portfolio],
            'education': [e.to_dict() for e in user.resume_education],
            'experience': [e.to_dict() for e in user.resume_experience],
            'achievements': [a.to_dict() for a in user.resume_achievements],
        })
    elif request.method == 'PUT':
        for k in ['job_title', 'bio', 'bitcoiner_question']:
            if k not in request.json:
                continue
            if request.json[k] is None:
                setattr(user, f'resume_{k}', None)
            else:
                length = len(request.json[k])
                max_length = getattr(m.User, f'resume_{k}').property.columns[0].type.length
                if length > max_length:
                    raise ValidationError(f"Please keep the {k} below {max_length} characters. You are currently at {length}.")
                setattr(user, f'resume_{k}', bleach.clean(request.json[k]))

        for k in ['desired_salary_usd']:
            if k not in request.json:
                continue
            if request.json[k] is None:
                setattr(user, f'resume_{k}', None)
            else:
                try:
                    setattr(user, f'resume_{k}', float(request.json[k]))
                except (ValueError, TypeError):
                    raise ValidationError(f"{k.replace('_', ' ')} is invalid.".capitalize())

        if 'skills' in request.json:
            existing_skills = {s.skill for s in user.resume_skills}
            new_skills = {s['skill'] for s in request.json['skills']}

            if len(new_skills) > 21:
                return jsonify({'message': "Please list at most 21 skills."}), 400

            if new_skills != existing_skills:
                for s in user.resume_skills:
                    if s.skill not in new_skills:
                        db.session.delete(s)
                for new_skill in new_skills:
                    if new_skill not in existing_skills:
                        db.session.add(m.UserResumeSkill(user_id=user.id, skill=new_skill))

        if 'portfolio' in request.json:
            existing_portfolio_urls = {p.url for p in user.resume_portfolio}
            new_portfolio_urls = {p['url'] for p in request.json['portfolio']}

            if len(new_portfolio_urls) > 21:
                return jsonify({'message': "Please list at most 21 portfolio links."}), 400

            if new_portfolio_urls != existing_portfolio_urls:
                for p in user.resume_portfolio:
                    if p.url not in new_portfolio_urls:
                        db.session.delete(p)
                for new_url in new_portfolio_urls:
                    if new_url not in existing_portfolio_urls:
                        db.session.add(m.UserResumePortfolio(user_id=user.id, url=new_url))

        for (singular, plural, cls) in [('education', 'education', m.UserResumeEducation), ('experience', 'experience', m.UserResumeExperience), ('achievement', 'achievements', m.UserResumeAchievement)]:
            if plural not in request.json:
                continue
            existing_resume_items = {i.key: i for i in getattr(user, f'resume_{plural}')}
            new_resume_items_to_edit = {i['key']: i for i in request.json[plural] if i['key']}
            new_resume_items_to_add = [i for i in request.json[plural] if not i['key']]

            for key, i in existing_resume_items.items():
                if key not in new_resume_items_to_edit:
                    db.session.delete(i)
            for key, i in new_resume_items_to_edit.items():
                existing_item = existing_resume_items.get(key)
                if existing_item:
                    try:
                        for k, v in cls.validate_dict(i).items():
                            setattr(existing_item, k, v)
                    except m.ValidationError as e:
                        return jsonify({'message': e.message}), 400
            for i in new_resume_items_to_add:
                try:
                    validated = cls.validate_dict(i)
                except m.ValidationError as e:
                    return jsonify({'message': e.message}), 400

                new_i = cls(**validated)
                new_i.generate_key()
                new_i.user = user
                db.session.add(new_i)

        db.session.commit()

        return jsonify({})

@api_blueprint.route('/api/users/me/messages', methods=['GET'])
@user_required
def get_messages(user):
    # by default we only return INTERNAL messages (to be shown in the UI),
    # but using the "via" parameter, we can request additional messages,
    # for example via=TWITTER_DM will return all messages sent to this user via TWITTER_DM
    via = request.args.get('via') or 'INTERNAL'

    if via == 'all':
        messages = user.messages
    else:
        messages = m.Message.query.filter_by(user_id=user.id, notified_via=via).all()

    return jsonify({'messages': [m.to_dict() for m in messages]})

@api_blueprint.route('/api/users/me/sales', methods=['GET'])
@user_required
def get_sales(user):
    sales = m.Sale.query.filter(m.Item.id == m.Sale.item_id, m.Item.seller_id == user.id).order_by(desc(m.Sale.requested_at)).all()

    return jsonify({'sales': [s.to_dict() for s in sales]})

@api_blueprint.route('/api/users/me/purchases', methods=['GET'])
@user_required
def get_purchases(user):
    purchases = m.Sale.query.filter(m.Sale.buyer_id == user.id).order_by(desc(m.Sale.requested_at)).all()

    return jsonify({'purchases': [p.to_dict() for p in purchases]})

@api_blueprint.route("/api/users/me/auctions",
    defaults={'cls': m.Auction, 'singular': 'auction', 'has_item': True, 'campaign_key': None},
    methods=['POST'])
@api_blueprint.route("/api/users/me/listings",
    defaults={'cls': m.Listing, 'singular': 'listing', 'has_item': True, 'campaign_key': None},
    methods=['POST'])
@api_blueprint.route("/api/users/me/campaigns",
    defaults={'cls': m.Campaign, 'singular': 'campaign', 'has_item': False, 'campaign_key': None},
    methods=['POST'])
@api_blueprint.route("/api/campaigns/<campaign_key>/auctions",
    defaults={'cls': m.Auction, 'singular': 'auction', 'has_item': True},
    methods=['POST'])
@api_blueprint.route("/api/campaigns/<campaign_key>/listings",
    defaults={'cls': m.Listing, 'singular': 'listing', 'has_item': True},
    methods=['POST'])
@user_required
def post_entity(user, cls, singular, has_item, campaign_key):
    campaign = None
    if campaign_key:
        campaign = m.Campaign.query.filter_by(key=campaign_key).first()
        if not campaign:
            return jsonify({'message': "Not found."}), 404

    for k in cls.REQUIRED_FIELDS:
        if k not in request.json:
            return jsonify({'message': f"Missing key: {k}."}), 400

    try:
        validated_item = m.Item.validate_dict(request.json, for_method='POST') if has_item else {}
        validated_entity = cls.validate_dict(request.json, for_method='POST')
    except m.ValidationError as e:
        return jsonify({'message': e.message}), 400

    item = None
    if has_item:
        item = m.Item(seller=user, **validated_item)
        db.session.add(item)
        db.session.commit()

    entity = cls(**validated_entity)
    entity.generate_key()
    if campaign:
        entity.campaign = campaign
    if item:
        entity.item = item
    if isinstance(entity, m.Campaign):
        entity.owner = user
    db.session.add(entity)
    db.session.commit()

    if isinstance(entity, m.Auction):
        # follow your own auctions!
        user_auction = m.UserAuction(user_id=user.id, auction_id=entity.id, following=True)
        db.session.add(user_auction)
        db.session.commit()

    return jsonify({'key': entity.key, singular: entity.to_dict(for_user=user.id)})

@api_blueprint.route('/api/auctions/active',
    defaults={'cls': m.Auction, 'plural': 'auctions', 'featured': False},
    methods=['GET'])
@api_blueprint.route('/api/listings/active',
    defaults={'cls': m.Listing, 'plural': 'listings', 'featured': False},
    methods=['GET'])
@api_blueprint.route('/api/campaigns/active',
    defaults={'cls': m.Campaign, 'plural': 'campaigns', 'featured': False},
    methods=['GET'])
@api_blueprint.route('/api/auctions/featured',
    defaults={'cls': m.Auction, 'plural': 'auctions', 'featured': True},
    methods=['GET'])
@api_blueprint.route('/api/listings/featured',
    defaults={'cls': m.Listing, 'plural': 'listings', 'featured': True},
    methods=['GET'])
def get_entities(cls, plural, featured):
    """
    Active auctions are all auctions currently running.
    Active listings are all listings that have been published and are still available for sale.
    Active campaigns are currently all campaigns. We don't have a way to mark a campaign as "ended", but that should eventually be added.
    Featured auctions/listings are subsets of the active auctions/listings:
        currently they simply exclude items that the moderators have marked as hidden,
        but we will eventually have a better algorithm to pick "featured" items.
    There are no "featured campaigns" because users can't (yet) add their own campaigns, so we only have our own.
        Also, since Campaign is not related to Items, it would not be able to take advantage of is_hidden.
        But an is_hiddden flad *could* be added to Campaign if needed.
    """
    entities = cls.query_all_active()
    if featured:
        entities = entities.filter((cls.item_id == m.Item.id) & ~m.Item.is_hidden)
    sorted_entities = sorted(entities.all(), key=(cls.featured_sort_key if featured else cls.sort_key))
    return jsonify({plural: [e.to_dict() for e in sorted_entities]})

@api_blueprint.route('/api/auctions/inactive',
    defaults={'cls': m.Auction, 'plural': 'auctions'},
    methods=['GET'])
@api_blueprint.route('/api/listings/inactive',
    defaults={'cls': m.Listing, 'plural': 'listings'},
    methods=['GET'])
def get_inactive_entities(cls, plural):
    """
    Inactive auctions are auctions that ended.
    Inactive listings are listings that used to be active, but available_quantity reached 0.
    """
    entities = cls.query_all_inactive()
    sorted_entities = sorted(entities.all(), key=cls.sort_key)
    return jsonify({plural: [e.to_dict() for e in sorted_entities]})

@api_blueprint.route('/api/auctions/<key>',
    defaults={'cls': m.Auction, 'singular': 'auction', 'has_item': True},
    methods=['GET', 'PUT', 'DELETE'])
@api_blueprint.route('/api/listings/<key>',
    defaults={'cls': m.Listing, 'singular': 'listing', 'has_item': True},
    methods=['GET', 'PUT', 'DELETE'])
@api_blueprint.route('/api/campaigns/<key>',
    defaults={'cls': m.Campaign, 'singular': 'campaign', 'has_item': False},
    methods=['GET', 'PUT', 'DELETE'])
def get_put_delete_entity(key, cls, singular, has_item):
    user = get_user_from_token(get_token_from_request())
    entity = cls.query.filter_by(key=key).first()
    if not entity:
        return jsonify({'message': "Not found."}), 404

    if request.method == 'GET':
        return jsonify({singular: entity.to_dict(for_user=(user.id if user else None))})
    else:
        is_changing_hidden_state = request.method == 'PUT' and 'is_hidden' in set(request.json.keys())
        is_changing_hidden_state_only = request.method == 'PUT' and set(request.json.keys()) == {'is_hidden'}

        if is_changing_hidden_state and not is_changing_hidden_state_only:
            return jsonify({'message': "When changing hidden state, nothing else can be changed in the same request."}), 400

        if not user:
            return jsonify({'message': "Unauthorized"}), 401
        if is_changing_hidden_state and not user.is_moderator:
            return jsonify({'message': "Unauthorized"}), 401

        if user.id != entity.owner_id and not is_changing_hidden_state:
            return jsonify({'message': "Unauthorized"}), 401

        if isinstance(entity, m.Auction) and not is_changing_hidden_state_only:
            reason = entity.get_not_editable_reason()
            if reason:
                return jsonify({'message': reason}), 403

        if request.method == 'PUT':
            # reorder media, if requested
            if 'media' in request.json:
                for media_item in request.json['media']:
                    media = m.Media.query.filter_by(item_id=entity.item_id, content_hash=media_item['hash']).first()
                    if media:
                        media.index = media_item['index']

            try:
                validated_item = m.Item.validate_dict(request.json, for_method='PUT') if has_item else {}
                validated = cls.validate_dict(request.json, for_method='PUT')
            except m.ValidationError as e:
                return jsonify({'message': e.message}), 400

            for k, v in validated_item.items():
                setattr(entity.item, k, v)
            for k, v in validated.items():
                setattr(entity, k, v)

            db.session.commit()

            return jsonify({})
        elif request.method == 'DELETE':
            if isinstance(entity, m.Auction | m.Listing):
                for sale in entity.sales:
                    sale.auction = sale.listing = None
            db.session.delete(entity)
            db.session.commit()

            return jsonify({})

@api_blueprint.route('/api/auctions/<key>/media',
    defaults={'cls': m.Auction, 'singular': 'auction'},
    methods=['POST'])
@api_blueprint.route('/api/listings/<key>/media',
    defaults={'cls': m.Listing, 'singular': 'listing'},
    methods=['POST'])
def post_media(key, cls, singular):
    user = get_user_from_token(get_token_from_request())

    if not user:
        return jsonify({'message': "Unauthorized"}), 401

    entity = cls.query.filter_by(key=key).first()
    if not entity:
        return jsonify({'message': "Not found."}), 404

    if user.id != entity.item.seller_id:
        return jsonify({'message': "Unauthorized"}), 401

    if isinstance(entity, m.Auction):
        reason = entity.get_not_editable_reason()
        if reason:
            return jsonify({'message': reason}), 403

    last_index = max([media.index for media in entity.item.media], default=0)
    index = last_index + 1

    f = request.files.get('media')
    if not f:
        return jsonify({'message': "No media file attached."}), 400

    original_filename = f.filename
    data = f.read()

    media = m.Media(item_id=entity.item_id, index=index)
    if not media.store(get_s3(), f"{singular}_{entity.key}_media_{index}", original_filename, data):
        return jsonify({'message': "Error fetching picture!"}), 400
    db.session.add(media)
    db.session.commit()

    return jsonify({'media': media.to_dict()})

@api_blueprint.route('/api/auctions/<key>/media/<content_hash>',
    defaults={'cls': m.Auction},
    methods=['DELETE'])
@api_blueprint.route('/api/listings/<key>/media/<content_hash>',
    defaults={'cls': m.Listing},
    methods=['DELETE'])
def delete_media(key, cls, content_hash):
    user = get_user_from_token(get_token_from_request())

    if not user:
        return jsonify({'message': "Unauthorized"}), 401

    entity = cls.query.filter_by(key=key).first()
    if not entity:
        return jsonify({'message': "Not found."}), 404

    if user.id != entity.item.seller_id:
        return jsonify({'message': "Unauthorized"}), 401

    if isinstance(entity, m.Auction):
        reason = entity.get_not_editable_reason()
        if reason:
            return jsonify({'message': reason}), 403

    media = m.Media.query.filter_by(item_id=entity.item_id, content_hash=content_hash).first()

    if not media:
        return jsonify({'message': "Media not found."}), 404

    db.session.delete(media)
    db.session.commit()

    return jsonify({})

@api_blueprint.route('/api/auctions/<key>/follow', methods=['PUT'])
@user_required
def follow_auction(user, key):
    auction = m.Auction.query.filter_by(key=key).first()
    if not auction:
        return jsonify({'message': "Not found."}), 404

    follow = bool(request.json['follow'])

    if auction.seller_id == user.id and not follow:
        return jsonify({'message': "Can't unfollow your own auctions!"}), 400

    user_auction = m.UserAuction.query.filter_by(user_id=user.id, auction_id=auction.id).one_or_none()
    if user_auction is None:
        message = "Started following the auction."
        user_auction = m.UserAuction(user_id=user.id, auction_id=auction.id, following=follow)
        db.session.add(user_auction)
    else:
        message = "Following the auction." if follow else "Unfollowed the auction."
        user_auction.following = follow
    db.session.commit()

    return jsonify({'message': message})

@api_blueprint.route('/api/auctions/<key>/publish',
    defaults={'cls': m.Auction, 'singular': 'auction', 'plural': 'auctions'},
    methods=['PUT'])
@api_blueprint.route('/api/listings/<key>/publish',
    defaults={'cls': m.Listing, 'singular': 'listing', 'plural': 'listings'},
    methods=['PUT'])
@user_required
def publish(user, key, cls, singular, plural):
    entity = cls.query.filter_by(key=key).first()
    if not entity:
        return jsonify({'message': "Not found."}), 404

    if entity.item.seller_id != user.id:
        return jsonify({'message': "Unauthorized"}), 401

    if not entity.campaign and not user.xpub:
        return jsonify({'message': "User did not set an XPUB."}), 400

    if request.json.get('twitter'):
        twitter = get_twitter()

        twitter_user = twitter.get_user(user.twitter_username)
        if not twitter_user:
            return jsonify({'message': "Twitter profile not found!"}), 400

        if not user.fetch_twitter_profile_image(twitter_user['profile_image_url'], get_s3()):
            return jsonify({'message': "Error fetching profile picture!"}), 500

        if not user.fetch_twitter_profile_banner(twitter_user['profile_banner_url'], get_s3()):
            return jsonify({'message': "Error fetching profile banner!"}), 500

        tweets = twitter.get_sale_tweets(twitter_user['id'], plural)
        tweet = None
        for t in sorted(tweets, key=lambda t: t['created_at'], reverse=True):
            # we basically pick the last tweet that matches the auction
            if t['auction_key'] == entity.key:
                tweet = t
                break

        if not tweet:
            return jsonify({'message': "Tweet not found."}), 400

        if entity.item.category != m.Category.Time.value:
            if not tweet['photos']:
                return jsonify({'message': "Tweet does not have any attached pictures."}), 400

            m.Media.query.filter_by(item_id=entity.item.id).delete()

            s3 = get_s3()
            for i, photo in enumerate(tweet['photos'], 1):
                media = m.Media(item_id=entity.item.id, index=i, twitter_media_key=photo['media_key'])
                if not media.store(s3, f"{singular}_{entity.key}_media_{i}", photo['url'], None):
                    return jsonify({'message': "Error fetching picture!"}), 400
                db.session.add(media)

        user.twitter_username_verified = True
        entity.twitter_id = tweet['id']

    entity.start_date = datetime.utcnow()

    if isinstance(entity, m.Auction):
        entity.end_date = entity.start_date + timedelta(hours=entity.duration_hours)

    db.session.commit()

    return jsonify({})

@api_blueprint.route('/api/auctions/<key>/bids', methods=['POST'])
@user_required
def post_bid(user, key):
    auction = m.Auction.query.filter_by(key=key).first()
    if not auction:
        return jsonify({'message': "Not found."}), 404

    if not auction.started:
        return jsonify({'message': "Auction not started."}), 403
    if auction.ended:
        return jsonify({'message': "Auction ended."}), 403

    amount = int(request.json['amount'])
    if amount > 2100000000:
        # TODO: should we change integer to bigint in the models?
        return jsonify({'message': "Max bidding: 21 BTC!"}), 400

    if not user.twitter_username_verified:
        return jsonify({'message': "Please verify your Twitter account before bidding!"}), 400

    top_bid = auction.get_top_bid()
    if top_bid and amount <= top_bid.amount:
        return jsonify({'message': f"The top bid is currently {top_bid.amount}. Your bid needs to be higher!"}), 400
    elif amount < auction.starting_bid:
        return jsonify({'message': f"Your bid needs to be equal or higher than {auction.starting_bid}, the starting bid."}), 400

    if auction.campaign: # TODO: for now we only support badges for campaigns
        try:
            btc2usd = btc2fiat.get_value('kraken')
        except Exception:
            return jsonify({'message': "Error fetching the exchange rate!"}), 500
        user_badges = {b['badge'] for b in user.get_badges()}
        for badge, badge_data in app.config['BADGES'].items():
            threshold_sats = usd2sats(badge_data['threshold_usd'], btc2usd)
            if amount >= threshold_sats:
                if badge not in user_badges:
                    return jsonify({'message': f"Can't bid more than ${badge_data['threshold_usd']} without a badge.", 'required_badge': badge}), 402

    if request.json.get('skip_invoice') == 'NEW_BADGE' and any(b['awarded_at'] >= datetime.utcnow() - timedelta(minutes=1) for b in user.get_badges()):
        # NB: we can skip the lightning invoice in the first minute after we have been awarded a badge,
        # this is so that the frontend can automatically re-place the previous bid which failed due to a badge being required
        payment_request = None
        auction.extend()
    else:
        response = get_lnd_client().add_invoice(value=app.config['LND_BID_INVOICE_AMOUNT'], expiry=app.config['LND_BID_INVOICE_EXPIRY'])
        payment_request = response.payment_request

    bid = m.Bid(auction=auction, buyer=user, amount=amount, payment_request=payment_request)
    if payment_request is None:
        bid.settled_at = datetime.utcnow()
    db.session.add(bid)

    started_following = False
    user_auction = m.UserAuction.query.filter_by(user_id=user.id, auction_id=auction.id).one_or_none()
    if user_auction is None:
        user_auction = m.UserAuction(user_id=user.id, auction_id=auction.id, following=True)
        db.session.add(user_auction)
        started_following = True
    else:
        if not user_auction.following:
            started_following = True
            user_auction.following = True
    db.session.commit()

    if payment_request:
        qr = BytesIO()
        pyqrcode.create(payment_request).svg(qr, omithw=True, scale=4)

        return jsonify({
            'payment_request': payment_request,
            'qr': qr.getvalue().decode('utf-8'),
            'messages': [
                "Your bid will be confirmed once you scan the QR code.",
            ] + (["Started following the auction."] if started_following else []),
        })
    else:
        return jsonify({'messages': ["Your bid is confirmed!"]}), 200

@api_blueprint.route('/api/badges/<int:badge>/buy', methods=['PUT'])
@user_required
def buy_badge(user, badge):
    if badge not in app.config['BADGES']:
        return jsonify({'message': "Badge not found."}), 404

    if not request.json.get('campaign_key'):
        # TODO: implement badge purchase without campaign
        return jsonify({'message': "campaign_key is required."}), 400

    campaign = m.Campaign.query.filter_by(key=request.json['campaign_key']).first()
    if not campaign:
        return jsonify({'message': "Campaign not found."}), 404

    try:
        btc2usd = btc2fiat.get_value('kraken')
    except Exception:
        return jsonify({'message': "Error fetching the exchange rate!"}), 500

    try:
        address = campaign.get_new_address()
        db.session.commit()
    except AddressGenerationError as e:
        return jsonify({'message': str(e)}), 500
    except MempoolSpaceError as e:
        return jsonify({'message': str(e)}), 500

    amount_usd = app.config['BADGES'][badge]['price_usd']
    amount_sats = usd2sats(amount_usd, btc2usd)

    sale = m.Sale(
        campaign_id=campaign.id,
        desired_badge=badge,
        buyer_id=user.id,
        address=address,
        price_usd=amount_usd,
        price=amount_sats,
        shipping_domestic=0,
        shipping_worldwide=0,
        quantity=1,
        amount=amount_sats,
        contribution_amount=0,
        contribution_payment_request=None,
        state=m.SaleState.CONTRIBUTION_SETTLED.value)
    db.session.add(sale)

    try:
        db.session.commit()
    except IntegrityError:
        return jsonify({'message': "Address already in use. Please try again."}), 500

    return jsonify({'sale': sale.to_dict()})

@api_blueprint.route('/api/listings/<key>/buy', methods=['PUT'])
@user_required
def buy_listing(user, key):
    listing = m.Listing.query.filter_by(key=key).first()
    if not listing:
        return jsonify({'message': "Not found."}), 404
    if not listing.started or listing.ended:
        return jsonify({'message': "Listing not active."}), 403

    if m.Sale.query.filter_by(listing_id=listing.id, buyer_id=user.id, state=m.SaleState.REQUESTED.value).first():
        return jsonify({'message': "You already have an active purchase for this listing."}), 403

    # NB: for now the quantity is always 1,
    # but storing this in the DB makes it easy in case we want to change this later on:
    # it would just be a matter of getting a quantity from the UI and sending it here to be used instead of 1.
    quantity = 1

    if listing.available_quantity < quantity:
        return jsonify({'message': "Not enough items in stock!"}), 400

    # NB: here we "lock" the quantity. it is given back if the sale expires
    listing.available_quantity -= quantity

    try:
        btc2usd = btc2fiat.get_value('kraken')
    except Exception:
        return jsonify({'message': "Error fetching the exchange rate!"}), 500

    try:
        if listing.campaign:
            address = listing.campaign.get_new_address()
        else:
            address = listing.item.seller.get_new_address()
    except AddressGenerationError as e:
        return jsonify({'message': str(e)}), 500
    except MempoolSpaceError as e:
        return jsonify({'message': str(e)}), 500

    price_sats = usd2sats(listing.price_usd, btc2usd)
    contribution_amount = listing.item.seller.get_contribution_amount(price_sats * quantity)

    if contribution_amount != 0:
        response = get_lnd_client().add_invoice(value=contribution_amount, expiry=app.config['LND_CONTRIBUTION_INVOICE_EXPIRY_LISTING'])
        contribution_payment_request = response.payment_request
    else:
        contribution_payment_request = None

    sale = m.Sale(item_id=listing.item.id, listing_id=listing.id,
        buyer_id=user.id,
        address=address,
        price_usd=listing.price_usd,
        price=price_sats,
        shipping_domestic=usd2sats(listing.item.shipping_domestic_usd, btc2usd),
        shipping_worldwide=usd2sats(listing.item.shipping_worldwide_usd, btc2usd),
        quantity=quantity,
        amount=(price_sats * quantity) - contribution_amount,
        contribution_amount=contribution_amount,
        contribution_payment_request=contribution_payment_request)
    if not contribution_payment_request:
        sale.state = m.SaleState.CONTRIBUTION_SETTLED.value
    db.session.add(sale)

    try:
        db.session.commit()
    except IntegrityError:
        return jsonify({'message': "Address already in use. Please try again."}), 500

    return jsonify({'sale': sale.to_dict()})

@api_blueprint.route("/api/users/<nym>/auctions",
    defaults={'plural': 'auctions'},
    methods=['GET'])
@api_blueprint.route("/api/users/<nym>/listings",
    defaults={'plural': 'listings'},
    methods=['GET'])
@api_blueprint.route("/api/users/<nym>/campaigns",
    defaults={'plural': 'campaigns'},
    methods=['GET'])
def get_user_entities(nym, plural):
    for_user = get_user_from_token(get_token_from_request())
    for_user_id = for_user.id if for_user else None

    if nym == 'me':
        user = for_user
    else:
        user = m.User.query.filter_by(nym=nym).first()

    if not user:
        return jsonify({'message': "User not found."}), 404

    def iter_entities():
        if plural == 'campaigns':
            for campaign in user.campaigns:
                yield campaign
        else:
            for item in user.items:
                for entity in getattr(item, plural):
                    yield entity

    entities = {}
    for entity in iter_entities():
        if entity.filter_state(request.args.get('filter'), for_user_id):
            entities[f"{plural}_{entity.id}"] = entity

    sorted_entities = sorted(entities.values(), key=lambda l: l.created_at, reverse=True)

    return jsonify({plural: [e.to_dict(for_user=for_user_id) for e in sorted_entities]})

@api_blueprint.route("/api/campaigns/<key>/auctions",
    defaults={'plural': 'auctions'},
    methods=['GET'])
@api_blueprint.route("/api/campaigns/<key>/listings",
    defaults={'plural': 'listings'},
    methods=['GET'])
def get_campaign_entities(key, plural):
    for_user = get_user_from_token(get_token_from_request())
    for_user_id = for_user.id if for_user else None

    campaign = m.Campaign.query.filter_by(key=key).first()

    if not campaign:
        return jsonify({'message': "Campaign not found."}), 404

    entities = []
    for entity in getattr(campaign, plural):
        if entity.filter_state(request.args.get('filter'), for_user_id):
            entities.append(entity)
    sorted_entities = sorted(entities, key=lambda e: e.created_at, reverse=True)

    return jsonify({plural: [e.to_dict(for_user=for_user_id) for e in sorted_entities]})

@api_blueprint.route("/api/campaigns/<key>/avatars/featured",
    methods=['GET'])
def get_campaign_featured_avatars(key):
    campaign = m.Campaign.query.filter_by(key=key).first()

    if not campaign:
        return jsonify({'message': "Campaign not found."}), 404

    avatars = {'auction_avatars': [], 'listing_avatars': []}

    for which_avatars, entities in [('auction_avatars', campaign.auctions), ('listing_avatars', campaign.listings)]:
        for entity in entities:
            if entity.started and not entity.item.is_hidden:
                avatar = {
                    'url': entity.item.seller.profile_image_url,
                    'entity_key': entity.key,
                    'featured_sort_key': entity.featured_sort_key()
                }
                avatars[which_avatars].append(avatar)
        avatars[which_avatars].sort(key=lambda a: a['featured_sort_key'], reverse=True)

        # NB: we do unique after we have sorted,
        # so an avatar is shown on the position of its highest scoring auction/listing if it has multiple!
        unique_avatars = []
        seen_avatars = set()
        for avatar in avatars[which_avatars]:
            if avatar['url'] not in seen_avatars:
                seen_avatars.add(avatar['url'])
                unique_avatars.append(avatar)
        avatars[which_avatars] = unique_avatars

    return jsonify(avatars)
