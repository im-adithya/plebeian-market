<script lang="ts">
    import { onDestroy, onMount } from 'svelte';
    import { toasts, ToastContainer } from 'svelte-toasts';
    import "../app.css";
    import { browser } from '$app/environment';
    import { page } from '$app/stores';
    import { user } from "$lib/stores";
    import { Info, Error, token } from "$sharedLib/stores";
    import type { Placement } from "$sharedLib/stores";
    import { getProfile } from "$lib/services/api";
    import Navbar from "$sharedLib/components/Navbar.svelte";
    import Footer from "$sharedLib/components/Footer.svelte";
    import LoginModalLightning from "$lib/components/auth/Modal.svelte";
    import LoginModal from "$sharedLib/components/login/Modal.svelte";

	const infoUnsubscribe = Info.subscribe(value => {
        if (value) {
            let description: string;
            let duration: number;
            let placement: Placement;
            if (typeof value === 'string') {
                description = value;
                duration = 4000;
                placement = window.screen.availWidth >= 1024 ? 'top-center' : 'bottom-right';
            } else {
                description = value.message;
                duration = value.duration;
                placement = value.placement;
            }

            toasts.add({
                description,
                duration,
                placement,
                type: 'info',
            });
            Info.set(null);
        }
	});
	onDestroy(infoUnsubscribe);

	const errorUnsubscribe = Error.subscribe(value => {
        if (value) {
            toasts.add({
                description: value,
                duration: 4000,
                placement: window.screen.availWidth >= 1024 ? 'top-center' : 'bottom-right',
                type: 'error'
            });
            Error.set(null);
        }
	});
	onDestroy(errorUnsubscribe);

    function fetchProfile(tokenValue) {
        getProfile(tokenValue, "me", (u) => { user.set(u); });
    }

    const tokenUnsubscribe = token.subscribe((t) => {
        if (t) {
            fetchProfile(t);
        } else {
            user.set(null);
        }
    });
    onDestroy(tokenUnsubscribe);

    onMount(async () => {
        if (browser) {
            const tokenLocalStorage = localStorage.getItem("token");
            token.set(tokenLocalStorage);
            fetchProfile(tokenLocalStorage);
        }
    });
</script>

<div class="h-screen pt-12 lg:pt-20 pb-20 mt-2">
    <Navbar isFrontOffice={false} />

    <div class="mx-auto mb-6 min-h-[80%] w-11/12 md:w-10/12">
        <slot />
    </div>

    {#if $page.url.pathname !== "/marketsquare"}
        <Footer isFrontOffice={false} />
    {/if}

    <ToastContainer let:data={data}>
        <div class:alert-error={data.type === 'error'} class:alert-info={data.type === 'info'} class="alert shadow-lg">
            <div>
                <span class:text-2xl={data.placement === 'center-center'}>{data.description}</span>
            </div>
          </div>
    </ToastContainer>
</div>

<LoginModal />
<LoginModalLightning />
