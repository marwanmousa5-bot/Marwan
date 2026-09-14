import { build, context } from 'esbuild';
import { existsSync } from 'node:fs';

const opts = {
  entryPoints: ['web-demo/src/main.tsx'],
  bundle: true,
  outfile: 'web-demo/public/app.js',
  format: 'iife',
  target: ['es2022'],
  jsx: 'automatic',
  minify: process.argv.includes('--minify'),
  sourcemap: false,
  logLevel: 'info',
  define: { 'process.env.NODE_ENV': '"production"' },
};

if (process.argv.includes('--watch')) {
  const ctx = await context(opts);
  await ctx.watch();
  console.log('watching…');
} else {
  await build(opts);
}
