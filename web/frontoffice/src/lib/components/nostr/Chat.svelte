<script lang="ts">
    import { onDestroy, onMount, afterUpdate } from 'svelte';
    import { Kind } from 'nostr-tools';
    import type { VitaminedMessage } from "$lib/components/nostr/types";
    import NostrNote from "$lib/components/nostr/Note.svelte";
    import NostrReplyNote from "$lib/components/nostr/ReplyNote.svelte";
    import { queryNip05, filterTags } from "$sharedLib/nostr/utils";
    import { type UserMetadata, subscribeMetadata, subscribeReactions, subscribeChannel, sendMessage } from "$sharedLib/services/nostr";
    import {NostrPublicKey, Error as ErrorStore} from "$sharedLib/stores";
    import {waitAndShowLoginIfNotLoggedAlready} from "$sharedLib/utils";
    import profilePicturePlaceHolder from "$sharedLib/images/profile_picture_placeholder.svg";
    import SendMessage from "$sharedLib/components/icons/SendMessage.svelte";

    const USE_MEDIA_CACHE = true;

    export let nostrRoomId: string;
    export let messageLimit: number = 60;
    export let messagesSince: number = 1672837281;  // January 4th 2023
    export let isMarketSquare: boolean = false;   // Makes the chatbox fixed to the bottom of the screen
    export let onReply = (message) => {nostrEventBeingRepliedTo = message};

    let nostrEventBeingRepliedTo = null;
    let textarea;
    let messages: VitaminedMessage[] = [];
    let sortedMessages: VitaminedMessage[] = [];
    let autoscroll: Boolean = true;
    let ignoreNextScrollEvent = false;

    function getMessage(messages: VitaminedMessage[], messageId) {
        for (const message of messages) {
            if (message.id === messageId) {
                return message;
            }
        }
    }

    const nostrQueriesBatchSize = 100;
    const nostrOrderMessagesDelay = 1500;
    const nostrBackgroundJobsDelay = 3000;

    let orderMessagesTimer: ReturnType<typeof setTimeout> | null = null;
    let backgroundJobsTimer: ReturnType<typeof setTimeout> | null = null;

    // null: to be requested
    // true: requested
    // UserProfile: the user profile
    let profileImagesMap = new Map<string, null | true | UserMetadata>();

    // null: to be requested
    // true: requested
    // false: the request errored out (so don't ask again)
    // other: the public key of the user as specified in the nip05 registry
    let nip05 = new Map<string, null | boolean | string>();

    // null: to be requested
    // true: requested
    let notesMap = new Map();

    export let onImgError = (imgElement, message) => {
        imgElement.onerror = "";
        imgElement.src = profilePicturePlaceHolder;

        // If the image is broken, let's put the placeholder image
        // in the profile so the next re-draws of the note does not
        // try to put the broken image again
        let profileInfo = profileImagesMap.get(message.pubkey)
        if (profileInfo && profileInfo !== null && profileInfo !== true) {
            profileInfo.picture = profilePicturePlaceHolder;
        }
    }

    function orderAndVitamineMessages() {
        let lastMessagePublicKey: string | null = null

        sortedMessages = messages
            .sort((a, b) => a.created_at >= b.created_at ? 1 : -1)
            .map(function(message) {
                if (lastMessagePublicKey === message.pubkey) {
                    message.samePubKey = true;
                }

                const profileInfo: null | true | UserMetadata = profileImagesMap.get(message.pubkey) || null;

                if (profileInfo !== null && profileInfo !== true) {
                    if (profileInfo.picture && USE_MEDIA_CACHE) {
                        profileInfo.picture = `https://media.nostr.band/thumbs/${message.pubkey.slice(-4)}/${message.pubkey}-picture-64`;
                    }

                    if (profileInfo.nip05) {
                        let nip05verificationPublicKey = nip05.get(profileInfo.nip05);

                        if (nip05verificationPublicKey === undefined) {
                            nip05.set(profileInfo.nip05, null);
                        } else if (nip05verificationPublicKey !== null) {
                            if (message.pubkey === nip05verificationPublicKey) {
                                let nip05Address = profileInfo.nip05;

                                if (nip05Address.startsWith('_@')) {
                                    message.nip05VerifiedAddress = nip05Address.substring(2);
                                } else {
                                    message.nip05VerifiedAddress = nip05Address;
                                }
                            }
                        }
                    }

                    message.profile = profileInfo;
                }

                // Tags for message type
                filterTags(message.tags, 'e').forEach(tag => {
                    const id = tag[1];

                    if (id !== nostrRoomId) {
                        let repliedToMessage = getMessage(messages, id);
                        if (repliedToMessage !== undefined) {
                            // Adding the reply id of the message to the replied message
                            let replies: Array<string> = repliedToMessage.replies || [];

                            if (!replies.includes(message.id)) {
                                replies.push(message.id);
                            }

                            repliedToMessage.replies = replies;

                            // Adding the replied message so we can show it alongside the message
                            message.repliedToMessage = repliedToMessage;
                        } else {
                            // If we don't have the message we're replying to (yet?), we show
                            // that this is a reply to a message #id
                            message.repliedToMessage = id;
                        }
                    }
                });

                // Image preview
                const match = message.content.match(/(https?:\/\/.*\.(?:png|jpg|jpeg|gif|svg))/i);
                const url = match ? match[1] : null;
                if (url !== null) {
                    message.imagePreviewUrl = url;
                }

                lastMessagePublicKey = message.pubkey;

                return message;
            });
    }

    function saveProfilePubkey(pubKey) {
        if (!profileImagesMap.has(pubKey)) {
            profileImagesMap.set(pubKey, null);
        }
    }

    function saveNoteId(noteId) {
        if (!notesMap.has(noteId)) {
            notesMap.set(noteId, null);
        }
    }

    function queryProfilesToNostrRelaysInBatches() {
        let profilesToGetLocal: string[] = [];

        let i = 0;

        for (const [key, profile] of profileImagesMap) {
            if (profile === null) {
                profileImagesMap.set(key, true);
                profilesToGetLocal.push(key);
                i++;

                if (i == nostrQueriesBatchSize) {
                    break;
                }
            }
        }

        if (profilesToGetLocal.length !== 0) {
            subscribeMetadata(profilesToGetLocal, (pk, m) => { profileImagesMap[pk] = m; });
        }
    }

    function queryNoteInformationInBatches() {
        let noteInfoToGetLocal: string[] = [];

        let i = 0;

        for (const [key, note] of notesMap) {
            if (note === null) {
                notesMap.set(key, true);
                noteInfoToGetLocal.push(key);
                i++;

                if (i == nostrQueriesBatchSize) {
                    break;
                }
            }
        }

        if (noteInfoToGetLocal.length === 0) {
            return;
        }

        subscribeReactions(noteInfoToGetLocal,
            (event) => {
                if (event.kind === Kind.Reaction) {
                    const likedEventId = event.tags.reverse().find((tag: any) => tag[0] === 'e')?.[1]; // last e tag is the liked post
                    if (!likedEventId) {
                        return;
                    }
                    const eventReaction: string = event.content;
                    const eventPubkey: string = event.pubkey;

                    for (const message of messages) {
                        if (message.id === likedEventId) {
                            if (message.reactions === undefined) {
                                message.reactions = new Map();
                            }

                            if (message.reactions.get(eventReaction) === undefined) {
                                message.reactions[eventReaction] = new Set();
                            }
                            message.reactions[eventReaction].add(eventPubkey);

                            break;
                        }
                    }
                }
            });
    }

    function queryNip05ServersForVerification() {
        nip05.forEach(async (value, key) => {
            if (value === null) {
                nip05.set(key, true);
                let nip05verificationResult = await queryNip05(key);
                nip05.set(key, nip05verificationResult);
            }
        });
    }

    function processMessagesPeriodically() {
        orderAndVitamineMessages();
        orderMessagesTimer = setTimeout(processMessagesPeriodically, nostrOrderMessagesDelay);
    }

    function doBackgroundJobsPeriodically() {
        queryProfilesToNostrRelaysInBatches();
        queryNoteInformationInBatches();
        queryNip05ServersForVerification();
        backgroundJobsTimer = setTimeout(doBackgroundJobsPeriodically, nostrBackgroundJobsDelay);
    }

    onMount(async () => {
        subscribeChannel(nostrRoomId, messageLimit, messagesSince,
            (newMessage) => {
                for (const message of messages) {
                    if (message.id === newMessage.id) {
                        return;
                    }
                }

                messages.push(newMessage);

                saveProfilePubkey(newMessage.pubkey);
                saveNoteId(newMessage.id);
            });

        processMessagesPeriodically();
        doBackgroundJobsPeriodically();

        window.addEventListener("scroll", function () {
            if (ignoreNextScrollEvent) {
                // Ignore this event because it was done programmatically
                ignoreNextScrollEvent = false;
                return;
            }

            // The user scrolled, so stop auto-scroll
            autoscroll = false;
        });
    });

    onDestroy(async () => {
        if (orderMessagesTimer !== null) {
            clearTimeout(orderMessagesTimer);
        }
        if (backgroundJobsTimer !== null) {
            clearTimeout(backgroundJobsTimer);
        }
    })

    const onKeyPress = e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            send();
        }
    }

    async function send() {
        if (!await waitAndShowLoginIfNotLoggedAlready()) {
            return;
        }

        const content = textarea.value.trim();

        if ($NostrPublicKey === null) {
            ErrorStore.set("You need to use a Nostr browser extension to be able to send messages to the chat.");
        } else if (content) {
            sendMessage(content, nostrRoomId, nostrEventBeingRepliedTo, null,
                () => {
                    nostrEventBeingRepliedTo = null;
                    textarea.value = '';
                    scrollToBottom();
                });
        }
    }

    const scrollToBottom = () => {
        ignoreNextScrollEvent = true;

        if (isMarketSquare) {
            window.scrollTo(0, document.body.scrollHeight);
        } else {
            // One div is for mobile scrolling. The other one is for desktop.
            // We need to scroll down both divs for now.
            const chatScrollableDiv = document.getElementById("chatScrollableDiv");
            if (chatScrollableDiv !== null) {
                chatScrollableDiv.scrollTop = chatScrollableDiv.scrollHeight;
            }

            const stallChatContainerDiv = document.getElementById("stallChatContainerDiv");
            if (stallChatContainerDiv !== null) {
                stallChatContainerDiv.scrollTop = stallChatContainerDiv.scrollHeight;
            }
        }
    }

    afterUpdate(() => {
        if (autoscroll && isMarketSquare) {
            scrollToBottom();
        }
    })
</script>

<div tabindex="0" class="collapse collapse-plus border border-gray-400/70 bg-base-100 rounded-box mb-4 lg:grid">
    <input type="checkbox" />
    <div class="collapse-title text-l font-medium"><b>Nostr</b> powered chat. Click here to see more info</div>
    <div class="collapse-content">
        <p class="mb-4">Nostr channel ID: {nostrRoomId}</p>
    </div>
</div>

<div class="flex flex-col mt-2 mb-6 pb-6 bg-cover bg-top bg-info-content-200 gap-2 overflow-x-hidden overflow-y-auto w-full"
     style="background-size: 5px 5px; background-image: radial-gradient(hsla(var(--bc)/.2) 0.5px,hsla(var(--b2)/1) 0.5px);" id="chatScrollableDiv">
    <div>
        {#each sortedMessages as message}
            <NostrNote {message} {onReply} {onImgError} />
        {/each}
    </div>
</div>

<div class="grid grid-cols-2 w-full lg:w-1/3 mx-auto p-3 inset-x-0 bottom-0 bg-black rounded-lg items-center" class:fixed={isMarketSquare}>
    {#if nostrEventBeingRepliedTo !== null}
        <div class="col-span-2">
            <NostrReplyNote message={nostrEventBeingRepliedTo} closeButton={true} {onReply} />
        </div>
    {/if}

    <div class="flex col-span-2">
        <textarea
            rows="1"
            id="nostrMessageSendText"
            autofocus={isMarketSquare}
            placeholder="Type your message"
            bind:this={textarea}
            on:keypress={onKeyPress}
            class="p-2 w-full bg-medium placeholder:text-light outline-0 resize-none"></textarea>

        <div on:click={send} on:keypress={onKeyPress}
             class="p-4 flex justify-center hover:scale-110 duration-300 transition-all cursor-pointer text-white">
            <div class="w-6 h-6"><SendMessage /></div>
        </div>
    </div>
</div>
