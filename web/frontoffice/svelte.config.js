import adapter from '@sveltejs/adapter-static';
import sveltePreprocess from 'svelte-preprocess';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	kit: {
		adapter: adapter({
			pages: 'build',
			assets: 'build',
			fallback: 'index.html',
			precompress: false,
			strict: true
		}),
		alias: {
			'$sharedLib': '../shared/src/lib',
		},
		prerender: {
			entries: [
				'*',
				'/p/[pubkey]',
				'/p/[pubkey]/stall/[stallId]',
				'/product/[product_id]'
			]
		},
		paths: {
			base: ''
		}
	},
	preprocess: sveltePreprocess()
};

export default config;
