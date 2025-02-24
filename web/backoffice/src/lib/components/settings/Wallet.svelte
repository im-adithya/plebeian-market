<script lang="ts">
    import { onMount } from 'svelte';
    import { page } from '$app/stores';
    import { ErrorHandler, putProfile, type UserProfile } from "$lib/services/api";
    import { user } from "$lib/stores";
    import { Info, token } from "$sharedLib/stores";
    import InfoIcon from "$sharedLib/components/icons/Info.svelte";
    import QuestionIcon from "$sharedLib/components/icons/Question.svelte";
    import InfoBox from "$lib/components/notifications/InfoBox.svelte";

    export let onSave: () => void = () => {};

    let wallet: string | null = null;
    let walletName: string | null = null;
    let lightningAddress: string | null = null;

    $: isValidWallet = wallet !== null && wallet !== "";
    $: isValidLightningAddress = lightningAddress !== null && lightningAddress !== "";

    $: saveActive = !saving && $user && isValidWallet && isValidLightningAddress && (lightningAddress !== $user.lightningAddress || wallet !== $user.wallet || walletName !== $user.walletName);

    let saving = false;
    function save() {
        saving = true;
        let p: UserProfile = {};
        if (wallet !== null) {
            p.wallet = wallet;
        }
        if (walletName !== null) {
            p.walletName = walletName;
        }
        if (lightningAddress !== null) {
            p.lightningAddress = lightningAddress;
        }
        putProfile($token, p,
            (u, _) => {
                user.set(u);
                Info.set("Your wallet information has been saved!");
                saving = false;
                onSave();
            },
            new ErrorHandler(true, () => saving = false));
    }

    onMount(async () => {
        if ($user) {
            wallet = $user.wallet ? $user.wallet : "";
            walletName = $user.walletName ? $user.walletName : "";
            lightningAddress = $user.lightningAddress ? $user.lightningAddress : "";
        }
    });
</script>

{#if $page.url.pathname === "/admin/account/settings"}
    <div class="text-2xl breadcrumbs">
        <ul>
            <li>Settings</li>
            <li>Wallet</li>
        </ul>
    </div>
{/if}

<div class="w-full flex items-center justify-center mt-24">
    <div class="max-w-lg">
        <InfoBox>
            Everyone has something of value... if it's not something physical, it is your skills or time.
            <br />
            To trade your value please hook up the two components of your sovereign magic money wallets! 
        </InfoBox>
    </div>
</div>

<div class="w-full flex items-center justify-center mt-8">
    <div class="form-control w-full max-w-lg">
        <label class="label" for="wallet">
            <span class="label-text flex"><span>XPUB / ZPUB</span><a href="/faq?question=xpub" target="_blank" class="lg:tooltip" data-tip="Click to read: How do I get the XPUB/YPUB/ZPUB from my wallet?"><span class="w-4 h-4"><QuestionIcon /></span></a></span>
            <div class="lg:tooltip" data-tip="We use your XPUB to generate addresses where you will receive Bitcoin payments.">
                <InfoIcon />
            </div>
        </label>
        <input bind:value={wallet} id="wallet" name="wallet" type="text" class="input input-bordered input-lg w-full" />
    </div>
</div>

<div class="w-full flex items-center justify-center mt-8">
    <div class="form-control w-full max-w-lg">
        <label class="label" for="walletName">
            <span class="label-text">Wallet name</span>
            <div class="lg:tooltip" data-tip="Give your wallet a name. This will later help you remember which wallet you used, if you have multiple.">
                <InfoIcon />
            </div>
        </label>
        <input bind:value={walletName} id="walletName" name="walletName" type="text" class="input input-bordered input-lg w-full" />
    </div>
</div>

<div class="w-full flex items-center justify-center mt-8">
    <div class="form-control w-full max-w-lg">
        <label class="label" for="stallName">
            <span class="label-text">Lightning address</span>
            <div class="lg:tooltip" data-tip="Lightning is great for fast small payments.">
                <InfoIcon />
            </div>
        </label>
        <input bind:value={lightningAddress} id="lightningAddress" name="lightningAddress" type="text" class="input input-bordered input-lg w-full" />
    </div>
</div>

<div class="flex justify-center items-center mt-4 h-15">
    <button id="save" class="btn btn-primary btn-lg" class:btn-disabled={!saveActive} on:click|preventDefault={save}>Save</button>
</div>
