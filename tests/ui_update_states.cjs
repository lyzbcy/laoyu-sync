const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const code = fs.readFileSync('ui/app.js', 'utf8');
const load = code.slice(code.indexOf('async function loadVersion()'), code.indexOf('$("btnCheckUpdate").onclick'));
const watch = code.slice(code.indexOf('async function watchUpdate()'), code.lastIndexOf('boot();'));
let cases = 0;
async function check(fn, stage, initiallyHidden, expectedHidden, expectedFastPoll) {
  const classes = new Set(initiallyHidden ? ['hidden'] : []);
  const elements = {};
  const polls = [];
  const ctx = {
    VERSION_TIMER: null,
    $: id => elements[id] ||= {classList: {
      add: x => classes.add(x), remove: x => classes.delete(x),
      toggle: (x, on) => on ? classes.add(x) : classes.delete(x)
    }},
    api: async (_method, path) => path === '/api/version'
      ? {version: '0.3.9', update: {enabled: true, has_update: false}}
      : {stage, percent: stage === 'complete' ? 100 : 0, message: stage},
    setTimeout: (_fn, delay) => polls.push(delay), clearTimeout: () => {},
    showChangelog: () => {}, beginUpdate: () => {}
  };
  vm.createContext(ctx);
  vm.runInContext(load + '\n' + watch, ctx);
  await ctx[fn]();
  assert.equal(classes.has('hidden'), expectedHidden, `${fn}/${stage}: visibility`);
  assert.equal(polls.includes(700), expectedFastPoll, `${fn}/${stage}: polling`);
  cases++;
}
(async () => {
  await check('loadVersion', 'complete', false, true, false);
  await check('loadVersion', 'idle', false, true, false);
  await check('loadVersion', 'failed', true, false, false);
  await check('loadVersion', 'downloading', false, false, false);
  await check('watchUpdate', 'complete', false, true, false);
  await check('watchUpdate', 'idle', false, true, false);
  await check('watchUpdate', 'failed', true, false, false);
  await check('watchUpdate', 'downloading', true, false, true);
  await check('watchUpdate', 'restarting', false, false, true);
  console.log(`${cases} state transition checks passed.`);
})().catch(e => { console.error(e); process.exitCode = 1; });

