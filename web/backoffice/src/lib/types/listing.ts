import type { IEntity } from "$lib/types/base";
import { Category, type Item, type AddedMedia, type Media, TIME_ITEM_DESCRIPTION_PLACEHOLDER } from "$lib/types/item";

export class Listing implements IEntity, Item {
    static SAVED_FIELDS = ['title', 'description', 'category', 'shipping_from', 'extra_shipping_domestic_usd', 'extra_shipping_worldwide_usd', 'price_usd', 'available_quantity'];

    endpoint = "listings";
    loader = {endpoint: this.endpoint, responseField: 'listing', fromJson};

    uuid: string = "";
    key: string = "";
    title: string = "";
    description: string = "";
    descriptionPlaceholder: string = "";
    category: string | null = null;
    shipping_from: string = "";
    extra_shipping_domestic_usd: number = 0;
    extra_shipping_worldwide_usd: number = 0;
    price_usd: number = 0;
    available_quantity: number = 0;
    start_date: Date | null = null;
    started: boolean = false;
    ended: boolean = false;
    media: Media[] = [];
    added_media: AddedMedia[] = [];
    campaign_key: string | null = null;
    campaign_name: string | null = null;
    is_mine: boolean = true;

    public validate() {
        return !(this.title.length === 0
            || this.description.length === 0
            || this.price_usd === null || this.price_usd === 0
            || this.available_quantity === null);
    }

    public toJson() {
        var json = {} as Record<string, any>;
        for (const k in this) {
            if (Listing.SAVED_FIELDS.indexOf(k) !== -1 && this[k] !== null) {
                json[k] = this[k];
            }
        }
        return JSON.stringify(json);
    }
}

export class TimeListing extends Listing {
    constructor() {
        super();
        this.category = Category.Time;
        this.descriptionPlaceholder = TIME_ITEM_DESCRIPTION_PLACEHOLDER;
    }
}

export function fromJson(json: any): Listing {
    var l = new Listing();
    for (var k in json) {
        if (k === 'start_date') {
            l.start_date = json[k] ? new Date(json[k]!) : null;
        } else {
            l[k] = json[k];
        }
    }
    return l;
}
