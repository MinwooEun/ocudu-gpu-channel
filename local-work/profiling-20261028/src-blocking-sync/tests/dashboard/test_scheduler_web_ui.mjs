import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

// Run the shipped renderers against analyzer output, without browser startup.
const html = readFileSync(new URL('../../use_cases/scheduler_benchmark/index.html', import.meta.url), 'utf8');
const script = html.split('<script type="module">')[1].split('</script>')[0]
  .replace(/^import .*;$/gm, '').split("try { state.chart = localStorage")[0];
const fixture = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const elements = new Map();
const labels = [];
const canvas = new Proxy({fillText: text => labels.push(text)}, {
  get: (target, key) => target[key] ?? (() => {}),
});
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    innerHTML: '', textContent: '', style: {setProperty() {}},
    addEventListener() {}, clientWidth: 900, clientHeight: 240,
    getContext: () => canvas,
  });
  return elements.get(id);
}
const context = vm.createContext({
  document: {getElementById: element, documentElement: {}},
  getComputedStyle: () => ({getPropertyValue: () => '#123456'}),
  window: {devicePixelRatio: 1}, fixture,
});
vm.runInContext(script, context);
vm.runInContext(`
  state.run = {benchmark: fixture.benchmark, software: {}, scenario: {}, live: false};
  state.report = fixture.report;
  renderHeader(); renderSheet(); renderBoard(); renderIntegrity();
  for (const chart of CHARTS) { state.chart = chart[0]; drawChart(); }
  scene3.ready = true; scene3.markers = {clear() {}};
  updateMarkers();
`, context);
const count = Object.keys(fixture.benchmark.cells).length;
const board = element('board').innerHTML;
assert.equal((board.match(/class="panel lane-head /g) || []).length, count);
assert.ok(labels.some(text => text.startsWith('cell a')));
assert.equal(labels.some(text => text.startsWith('cell b')), count === 2);
for (const id of ['sheet', 'board', 'sceneOverlay', 'sceneLegend', 'integrity']) {
  const rendered = element(id).innerHTML;
  assert.ok(!rendered.includes('undefined'), `${id} contains undefined`);
  if (count === 1) {
    assert.ok(!/gnb1|ue2|ue3|cell b|Broker b|both cells|Both brokers/.test(rendered), id);
  }
}
assert.equal(board.includes('Paired over'), count === 2);
console.log(`Scheduler dashboard renders ${count} active cell(s), all charts and scene labels`);
