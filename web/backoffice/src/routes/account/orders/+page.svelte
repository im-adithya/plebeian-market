<script lang="ts">
    import { fromJson as orderFromJson } from "$lib/types/order";
    import ListView, { ListViewStyle } from "$lib/components/ListView.svelte";
    import OrderRow from "$lib/components/OrderRow.svelte";
</script>

<h3 class="lg:text-8xl font-bold text-center text-4xl my-20">My received orders</h3>

<div class="lg:w-2/3 mx-auto">
    <ListView
        loader={{endpoint: "users/me/orders", responseField: 'orders', fromJson: orderFromJson}}
        columns={["UUID", "Date", "Total Sats / Fiat", "Received sats", "Tx", "Status"]}
        card={OrderRow}
        editor={null}
        style={ListViewStyle.Table} />
</div>
