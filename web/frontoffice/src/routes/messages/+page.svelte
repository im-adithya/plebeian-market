<script>
    import {onMount} from "svelte";
    import {afterNavigate} from "$app/navigation";
    import { page } from '$app/stores'
    import {nip19} from "nostr-tools";
    import {sendPrivateMessage} from "$sharedLib/services/nostr";
    import {NostrPublicKey, privateMessages} from "$sharedLib/stores";
    import SimpleNote from "$lib/components/nostr/SimpleNote.svelte";
    import profilePicturePlaceHolder from "$sharedLib/images/profile_picture_placeholder.svg";
    import SendMessage from "$sharedLib/components/icons/SendMessage.svelte";
    import ArrowLeft from "$sharedLib/components/icons/ArrowLeft.svelte";
    import Titleh1 from "$sharedLib/components/layout/Title-h1.svelte";
    import {requestLoginModal, waitAndShowLoginIfNotLoggedAlready} from "$sharedLib/utils";

    let selectedConversationPubkey = null;
    let sortedConversations;
    let sortedMessages = [];
    let chatTextareaMobile;
    let chatTextareaDesktop;
    let newConversationPubkey;

    // Messages
    $: {
        if (selectedConversationPubkey && $privateMessages.human && $privateMessages.human[selectedConversationPubkey]) {
            sortedMessages = Object.entries($privateMessages.human[selectedConversationPubkey].messages).sort((a, b) => {
                return a[1].created_at - b[1].created_at;
            });

            scrollToBottom();

            const maxTimestampConversation = $privateMessages.human[selectedConversationPubkey].maxTimestamp;
            let messagesStorage = localStorage.getItem('readMessages');
            let messages = JSON.parse(messagesStorage) ?? {};

            if (maxTimestampConversation > (messages[selectedConversationPubkey] ?? 0)) {
                messages[selectedConversationPubkey] = maxTimestampConversation;

                localStorage.setItem('readMessages', JSON.stringify(messages));

                // Fire private messages reactivity manually
                $privateMessages.human[selectedConversationPubkey].maxTimestamp = $privateMessages.human[selectedConversationPubkey].maxTimestamp;
            }
        } else {
            sortedMessages = [];
        }
    }

    // Conversations
    $: {
        if ($privateMessages.human) {
            sortedConversations = Object.entries($privateMessages.human).sort((a, b) => {
                return b[1].maxTimestamp - a[1].maxTimestamp;
            });
        } else {
            sortedConversations = [];
        }
    }

    const onKeyPress = e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            send();
        }
    }

    async function send() {
        const contentMobile = chatTextareaMobile.value.trim();
        const contentDesktop = chatTextareaDesktop.value.trim();
        let content = '';

        if (contentMobile && contentMobile.length > 0) {
            content += contentMobile;
        } else if (contentDesktop && contentDesktop.length > 0) {
            content += contentDesktop;
        }

        if (content.length > 0) {
            let merchantPrivateKey;
            if ($privateMessages.human[selectedConversationPubkey] && $privateMessages.human[selectedConversationPubkey].merchantPrivateKey) {
                merchantPrivateKey = $privateMessages.human[selectedConversationPubkey].merchantPrivateKey;
            }

            await sendPrivateMessage(selectedConversationPubkey, content, merchantPrivateKey,
                async (relay) => {
                    chatTextareaMobile.value = '';
                    chatTextareaDesktop.value = '';
                    console.debug('-------- Private message accepted by relay:', relay);
                }
            );
        }
    }

    function selectConversation(publicKey) {
        if (!publicKey) {
            return;
        }

        selectedConversationPubkey = publicKey;
    }

    async function scrollToBottom() {
        await new Promise(resolve => setTimeout(resolve, 150));

        let chatScrollableDivMobile = document.getElementById("conversationMessagesMobile");
        if (chatScrollableDivMobile !== null) {
            chatScrollableDivMobile.scrollTop = chatScrollableDivMobile.scrollHeight;
        }

        let chatScrollableDivDesktop = document.getElementById("conversationMessagesDesktop");
        if (chatScrollableDivDesktop !== null) {
            chatScrollableDivDesktop.scrollTop = chatScrollableDivDesktop.scrollHeight;
        }
    }

    export let onImgError = (imgElement) => {
        imgElement.onerror = "";
        imgElement.src = profilePicturePlaceHolder;
    }

    afterNavigate(async () => {
        await waitAndShowLoginIfNotLoggedAlready();
    });

    onMount(async () => {
        const newMessagePubKey = $page.url.searchParams.get('newMessagePubKey');

        if (newMessagePubKey && newMessagePubKey.length === 64) {
            newConversationPubkey = newMessagePubKey;
            selectConversation(newMessagePubKey);
        }
    });
</script>

<svelte:head>
    <title>Private Messages</title>
</svelte:head>


<!-- Title for desktop: always visible -->
<div class="hidden md:block">
    <Titleh1>Private Messages</Titleh1>
</div>

<!-- Title for mobile: visible only in conversation view -->
{#if !selectedConversationPubkey}
    <div class="block lg:hidden">
        <Titleh1>Private Messages</Titleh1>
    </div>
{/if}

{#if $NostrPublicKey}
    {#if newConversationPubkey || sortedConversations.length > 0}
        <!-- Desktop -->
        <div class="hidden lg:flex h-[46rem]">
            <div class="block w-1/3 p-1 menu card h-auto max-h-full gap-2 rounded-box bg-cover bg-top bg-base-300 bg-info-content-200 overflow-y-auto overflow-x-hidden
                        scrollbar:!w-1.5 scrollbar:!h-1.5 scrollbar:bg-transparent scrollbar-track:!bg-slate-100 scrollbar-thumb:!rounded scrollbar-thumb:!bg-slate-300
                        scrollbar-track:!rounded dark:scrollbar-track:!bg-slate-500/[0.16] dark:scrollbar-thumb:!bg-slate-500/50 hover:scrollbar-thumb:!bg-slate-400/80 lg:supports-scrollbars:pr-2">
                {#if newConversationPubkey && !$privateMessages.human[newConversationPubkey]}
                    <li class="rounded-lg w-full"
                        class:bg-accent={selectedConversationPubkey === newConversationPubkey}
                        on:click={() => selectConversation(newConversationPubkey)}
                    >
                        <div class="w-full">
                            <div class="avatar indicator">
                                <div class="w-16 rounded-full">
                                    <img src="{profilePicturePlaceHolder}" on:error={(event) => onImgError(event.srcElement)} />
                                </div>
                            </div>
                            <div class="truncate">
                                New conversation: {nip19.npubEncode(newConversationPubkey)}
                            </div>
                        </div>
                    </li>
                {/if}

                {#each sortedConversations as [publicKey, conversation]}
                    <li class="rounded-lg w-full"
                        class:bg-accent={selectedConversationPubkey === publicKey}
                        class:text-black={selectedConversationPubkey === publicKey}
                        on:click={() => selectConversation(publicKey)}
                    >
                        <div class="w-full">
                            <div class="avatar indicator">
                                {#if conversation.unreadMessages}
                                    <span class="indicator-item badge badge-sm badge-error">
                                        {conversation.unreadMessages}
                                    </span>
                                {/if}
                                <div class="w-16 rounded-full">
                                    <img src="{conversation.picture ?? profilePicturePlaceHolder}" on:error={(event) => onImgError(event.srcElement)} />
                                </div>
                            </div>
                            <div class="text-lg truncate">
                                {conversation.name ?? nip19.npubEncode(publicKey)}
                            </div>
                            <div>
                                {#if conversation && conversation.merchantPrivateKey}
                                    <span class="indicator-item badge badge-sm badge-info">
                                        Received on the stall
                                    </span>
                                {/if}
                            </div>
                        </div>
                    </li>
                {/each}
            </div>

            <div class="divider lg:divider-horizontal"></div>

            <div class="flex flex-col flex-grow w-full p-4 gap-2 card bg-base-300 rounded-box bg-cover bg-top bg-info-content-200 overflow-x-hidden overflow-y-auto            scrollbar:!w-1.5 scrollbar:!h-1.5 scrollbar:bg-transparent scrollbar-track:!bg-slate-100 scrollbar-thumb:!rounded scrollbar-thumb:!bg-slate-300 scrollbar-track:!rounded dark:scrollbar-track:!bg-slate-500/[0.16] dark:scrollbar-thumb:!bg-slate-500/50 lg:supports-scrollbars:pr-2 hover:scrollbar-thumb:!bg-slate-400/80"
                 id="conversationMessagesDesktop" style="background-size: 5px 5px; background-image: radial-gradient(hsla(var(--bc)/.2) 0.5px,hsla(var(--b2)/1) 0.5px);">
                {#if selectedConversationPubkey}
                    {#each sortedMessages as [publicKey, message]}
                        {#if typeof message === 'object'}
                            <SimpleNote {message} />
                        {/if}
                    {/each}

                    <div class="grid grid-cols-2 w-screen lg:w-2/3 p-3 bg-gray-300 dark:bg-black rounded-lg items-center inset-x-0 bottom-0 mx-auto mt-auto">
                        <div class="flex col-span-2">
                        <textarea
                                rows="1"
                                autofocus
                                placeholder="Type your message"
                                bind:this={chatTextareaDesktop}
                                on:keypress={onKeyPress}
                                class="p-2 w-full bg-medium placeholder:text-light outline-0 resize-none"></textarea>

                            <div on:click={send} on:keypress={onKeyPress}
                                 class="p-4 flex justify-center hover:scale-110 duration-300 transition-all cursor-pointer text-black dark:text-white">
                                <div class="w-7 h-7"><SendMessage /></div>
                            </div>
                        </div>
                    </div>
                {:else}
                    <p class="m-6">Choose a conversation to see the messages.</p>
                {/if}
            </div>
        </div>

        <!-- Mobile -->
        {#if !selectedConversationPubkey}
            <div class="lg:hidden flex w-full h-auto p-1 max-h-full gap-2 menu card rounded-box bg-cover bg-top bg-base-300 bg-info-content-200 overflow-y-auto overflow-x-hidden
                        scrollbar:!w-1.5 scrollbar:!h-1.5 scrollbar:bg-transparent scrollbar-track:!bg-slate-100 scrollbar-thumb:!rounded scrollbar-thumb:!bg-slate-300
                        scrollbar-track:!rounded dark:scrollbar-track:!bg-slate-500/[0.16] dark:scrollbar-thumb:!bg-slate-500/50 hover:scrollbar-thumb:!bg-slate-400/80">
                {#if newConversationPubkey && !$privateMessages.human[newConversationPubkey]}
                    <li class="rounded-lg w-full"
                        on:click={() => selectConversation(newConversationPubkey)}
                    >
                        <div class="w-full">
                            <div class="avatar indicator">
                                <div class="w-16 rounded-full">
                                    <img src="{profilePicturePlaceHolder}" on:error={(event) => onImgError(event.srcElement)} />
                                </div>
                            </div>
                            <div class="truncate">
                                New conversation: {nip19.npubEncode(newConversationPubkey)}
                            </div>
                        </div>
                    </li>
                {/if}

                {#each sortedConversations as [publicKey, conversation]}
                    <li class="rounded-lg w-full"
                        class:bg-primary={selectedConversationPubkey === publicKey}
                        on:click={() => selectConversation(publicKey)}
                    >
                        <div class="w-full">
                            <div class="avatar indicator">
                                {#if conversation.unreadMessages}
                                <span class="indicator-item badge badge-sm badge-error">
                                    {conversation.unreadMessages}
                                </span>
                                {/if}
                                <div class="w-16 rounded-full">
                                    <img src="{conversation.picture ?? profilePicturePlaceHolder}" on:error={(event) => onImgError(event.srcElement)} />
                                </div>
                            </div>
                            <div class="text-lg truncate">
                                {conversation.name ?? nip19.npubEncode(publicKey)}
                            </div>
                        </div>
                    </li>
                {/each}
            </div>

        {:else}
            <div class="lg:hidden flex w-full mx-auto pt-6 pb-1 leading-none">
                <div class="w-10 mr-4 mt-1 cursor-pointer" on:click={() => selectedConversationPubkey = null}>
                    <ArrowLeft />
                </div>

                {#if newConversationPubkey && !$privateMessages.human[newConversationPubkey]}
                    <div class="avatar indicator">
                        <div class="w-12 h-12 mr-3 rounded-full">
                            <img src="{profilePicturePlaceHolder}" />
                        </div>
                    </div>

                    <div class="text-base truncate">
                        <p>New conversation:</p>
                        <p>{nip19.npubEncode(newConversationPubkey)}</p>
                    </div>

                {:else}

                    {#each sortedConversations as [conversationPublicKey, conversation]}
                        {#if selectedConversationPubkey === conversationPublicKey}
                            <div class="avatar indicator align-bottom">
                                <div class="w-12 h-12 mr-3 rounded-full">
                                    <img src="{conversation.picture ?? profilePicturePlaceHolder}" on:error={(event) => onImgError(event.srcElement)} />
                                </div>
                            </div>

                            <div class="flex flex-grow w-0 mt-2 text-xl truncate">
                                {conversation.name ?? nip19.npubEncode(selectedConversationPubkey)}
                            </div>
                        {/if}
                    {/each}
                {/if}
            </div>

            <div class="lg:hidden flex h-full gap-2 card bg-base-300 rounded-box bg-cover bg-top bg-info-content-200 overflow-x-hidden overflow-y-auto
                        scrollbar:!w-1.5 scrollbar:!h-1.5 scrollbar:bg-transparent scrollbar-track:!bg-slate-100 scrollbar-thumb:!rounded scrollbar-thumb:!bg-slate-300
                        scrollbar-track:!rounded dark:scrollbar-track:!bg-slate-500/[0.16] dark:scrollbar-thumb:!bg-slate-500/50 hover:scrollbar-thumb:!bg-slate-400/80"
                 id="conversationMessagesMobile" style="background-size: 5px 5px; background-image: radial-gradient(hsla(var(--bc)/.2) 0.5px,hsla(var(--b2)/1) 0.5px);">

                <div class="mt-2 ml-1">
                    {#each sortedMessages as [publicKey, message]}
                        {#if typeof message === 'object'}
                            <SimpleNote {message} />
                        {/if}
                    {/each}
                </div>

                <div class="flex w-full mx-auto p-3 bg-black rounded-lg items-center bottom-0 content-end col-span-2 mt-auto">
                    <textarea
                            rows="1"
                            autofocus
                            placeholder="Type your message"
                            bind:this={chatTextareaMobile}
                            on:keypress={onKeyPress}
                            class="p-2 w-full bg-medium placeholder:text-light outline-0 resize-none"></textarea>

                    <div on:click={send} on:keypress={onKeyPress}
                         class="p-4 flex justify-center hover:scale-110 duration-300 transition-all cursor-pointer text-white">
                        <div class="w-6 h-6"><SendMessage /></div>
                    </div>
                </div>
            </div>
        {/if}

    {:else}
        <div class="p-4 justify-center">
            <p>You don't have any message yet.</p>
        </div>
    {/if}
{:else}
    <div class="p-4 justify-center">
        <p>You have to login to see your messages.</p>
        <button class="btn btn-info mt-4 justify-center" on:click={() => requestLoginModal()} on:keypress={() => requestLoginModal()}>Login</button>
    </div>
{/if}
