<script lang="ts">
    import { onMount } from 'svelte';
    import { ErrorHandler, deleteEntity, putPublish } from "$lib/services/api";
    import { user } from "$lib/stores";
    import { token, Info } from "$sharedLib/stores";
    import type { IEntity } from "$lib/types/base";
    import { Auction } from "$lib/types/auction";
    import { Listing } from "$lib/types/listing";
    import type { Item } from "$lib/types/item";
    import AmountFormatter, { AmountFormat } from "$lib/components/AmountFormatter.svelte";
    import Countdown, { CountdownStyle } from "$lib/components/Countdown.svelte";
    import ErrorBox from "$lib/components/notifications/ErrorBox.svelte";
    import Pencil from "$sharedLib/components/icons/Pencil.svelte";
    import Trash from "$sharedLib/components/icons/Trash2.svelte";

    export let isEditable = false;
    export let showCampaign = false;

    export let entity: IEntity;
    $: item = <Item>(<unknown>entity);
    $: hasWallet = ($user && ($user.wallet !== null || $user.lightningAddress !== null));

    $: url = item.started ? `/product/${item.uuid}` : null;
    $: topBid = (item instanceof Auction) ? item.topBid() : null;

    let box; // the whole box representing this item (the HTML Element)

    export let onEdit = (_: Item) => {};
    export let onEntityChanged = () => {};

    let inRequest = false;
    function publish() {
        inRequest = true;
        putPublish($token, item.endpoint, item.key,
            () => {
                inRequest = false;
                if (item instanceof Auction) {
                    user.update(u => { if (u) { u.hasActiveAuctions = true; } return u; });
                    Info.set("Your auction is now active...");
                } else if (item instanceof Listing) {
                    user.update(u => { if (u) { u.hasActiveListings = true; } return u; });
                    Info.set("Your listing is now active...");
                }
                onEntityChanged();
            },
            new ErrorHandler(true, () => inRequest = false));
    }

    function del() {
        if (window.confirm("Are you sure?")) {
            deleteEntity($token, entity, onEntityChanged);
        }
    }

    onMount(async () => {
        if (item && window.location.hash === `#item-${item.key}`) {
            window.scrollTo(0, box.offsetTop);
        }
    });
</script>

<div bind:this={box} class="group">
    {#if isEditable}
        <div class="flex flex-row-reverse gap-2 invisible group-hover:visible">
            <div class="btn-xs"></div>
                {#if item instanceof Listing || (item instanceof Auction && (!item.started || (item.bids.length === 0)))}
                    <button class="btn btn-primary btn-circle btn-xs" on:click={del}><Trash /></button>
                    <button class="btn btn-primary btn-circle btn-xs" on:click={() => onEdit(item)}><Pencil /></button>
                {/if}
        </div>
    {/if}

    <div class="card bg-base-300 max-w-full overflow-hidden shadow-xl my-3 mx-3">
        <a href={url}>
            <figure class="h-auto flex justify-center">
                {#if item.media.length !== 0}
                    <img class="object-contain" src={item.media[0].url} alt="Item" />
                {/if}
            </figure>
        </a>
        <div class="card-body">
            <h2 class="card-title mb-2 lg:text-3xl text-2xl font-bold">
                <a href={url}>{item.title}</a>
            </h2>
            {#if showCampaign && item.campaign_name !== null}
                <div class="badge badge-primary"><a href="/campaigns/{item.campaign_key}"><nobr>{item.campaign_name} campaign</nobr></a></div>
            {/if}
            {#if item instanceof Auction}
                <div class="badge badge-secondary">auction</div>
            {:else if item instanceof Listing}
                <div class="badge badge-secondary">fixed price</div>
            {/if}
            {#if item instanceof Auction}
                {#if item.started && !item.ended}
                    <Countdown totalSeconds={item.ends_in_seconds} style={CountdownStyle.Compact} />
                {:else if item.ended}
                    <div class="badge badge-primary">ended</div>
                {/if}
            {:else if item instanceof Listing}
                {#if item.available_quantity === 0}
                    <div class="badge badge-primary">sold out</div>
                {/if}
            {/if}
            <p class="text-xs">
                {#if item instanceof Auction}
                    {#if item.has_winner && item.winner}
                        Winner: <a rel="external" class="link" href="/stall/{item.winner.nym}">{item.winner.nym}</a>
                        <br />
                        Amount: <AmountFormatter satsAmount={item.topAmount()} />
                    {:else if item.bids.length !== 0}
                        Bids: {item.bids.length}
                        <br />
                        {#if topBid && topBid.buyer}
                            Top bid: <AmountFormatter satsAmount={topBid.amount} format={AmountFormat.Sats} />
                            <br />
                            Bidder: <a rel="external" class="link" href="/stall/{topBid.buyer.nym}">{topBid.buyer.nym}</a>
                        {/if}
                    {:else if !item.ended}
                      <div>
                        <p>
                          Starting bid:
                        </p>
                        <p class="text-2xl font-bold">
                          <AmountFormatter satsAmount={item.starting_bid} format={AmountFormat.Sats} />
                        </p>
                      </div>
                    {/if}
                {:else if item instanceof Listing}
                  <!-- PRICE IN DOLLARS AND SATS -->
                  <div>
                    <p>
                      Price:
                    </p>
                    <p class="lg:text-2xl text-xl font-bold">
                      ${item.price_usd}
                    </p>
                    <p class="text-2xl font-bold">
                      ~<AmountFormatter usdAmount={item.price_usd} format={AmountFormat.Sats} />
                    </p>
                  </div>
                  <!-- STOCK -->
                  <div class="mt-4">
                    <p>
                      Stock:
                    </p>
                    <p class="lg:text-2xl text-xl font-bold">
                      {item.available_quantity}
                    </p>
                  </div>
                {/if}
            </p>
            <div class="max-h-52 overflow-hidden">
                {item.description}
            </div>
            {#if !item.started}
                {#if !hasWallet}
                    <ErrorBox>
                        <span>Please <a href="/admin/account/settings#page=WALLET&onsave=mystall" class="link">configure your wallet</a> before you continue!</span>
                    </ErrorBox>
                {/if}
                <button class="btn btn-primary" class:btn-disabled={inRequest} on:click|preventDefault={publish}>Publish</button>
            {/if}
        </div>
    </div>
</div>
