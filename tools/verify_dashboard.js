// verify_dashboard.js —— 用最小 DOM 垫片验证大屏的 JS 逻辑真的能跑
// Chrome headless 在本机沙箱里起不来，所以用 Node 模拟 DOM，
// 跑一遍 update() 和所有渲染函数，确认没有运行时错误、数值合理。

const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(
  path.join(__dirname, '..', 'out', 'dashboard.html'), 'utf8');
const m = html.match(/<script>([\s\S]*)<\/script>/);
if (!m) { console.error('❌ 找不到 script 块'); process.exit(1); }
const js = m[1];

// ---------------- 最小 DOM 垫片 ----------------
const elements = {};
function makeEl(sel) {
  const el = {
    _sel: sel,
    _html: '',
    _text: '',
    value: '1',
    style: {},
    dataset: {},
    classList: {
      _s: new Set(),
      add(c) { this._s.add(c); },
      remove(c) { this._s.delete(c); },
      contains(c) { return this._s.has(c); },
    },
    clientWidth: 900,
    clientHeight: 190,
    width: 900,
    height: 190,
    listeners: {},
    addEventListener(ev, fn) { this.listeners[ev] = fn; },
    getContext() {
      // canvas 2d 上下文：所有绘图调用都是空操作
      const noop = () => {};
      return new Proxy({
        scale: noop, clearRect: noop, beginPath: noop, moveTo: noop,
        lineTo: noop, stroke: noop, fill: noop, fillRect: noop,
        fillText: noop, arc: noop, setLineDash: noop,
        measureText: () => ({ width: 20 }),
      }, {
        get(t, k) {
          if (k in t) return t[k];
          return noop;
        },
        set(t, k, v) { t[k] = v; return true; },
      });
    },
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); },
    get textContent() { return this._text; },
    set textContent(v) { this._text = String(v); },
    get onclick() { return this._onclick; },
    set onclick(fn) { this._onclick = fn; },
  };
  return el;
}
function q(sel) {
  if (!elements[sel]) elements[sel] = makeEl(sel);
  return elements[sel];
}
const allStores = [];
const allJumps = [];

global.document = {
  querySelector: q,
  querySelectorAll(sel) {
    if (sel === '.store') return allStores;
    if (sel === '.jump') return allJumps;
    return [];
  },
};
global.window = {
  devicePixelRatio: 2,
  addEventListener() {},
};
global.$ = q;

// 预先造出快捷按钮（HTML 里有 6 个 data-ch）
[1, 1601, 2100, 3001, 4201, 4953].forEach(ch => {
  const b = makeEl('.jump');
  b.dataset = { ch: String(ch) };
  allJumps.push(b);
});

// ---------------- 执行 ----------------
let failures = [];
try {
  // 用 Function 包一层，把 D 暴露出来检查
  const wrapped = js + '\n; global.__D = D; global.__levelAt = levelAt;'
                 + ' global.__realmAt = realmAt; global.__update = update;';
  new Function(wrapped)();
} catch (e) {
  console.error('❌ JS 执行失败:', e.message);
  console.error(e.stack.split('\n').slice(0, 5).join('\n'));
  process.exit(1);
}
console.log('✅ JS 执行无异常');

const D = global.__D;
const levelAt = global.__levelAt;
const realmAt = global.__realmAt;
const update = global.__update;

// ---------------- 断言 ----------------
function check(name, cond, extra) {
  if (cond) {
    console.log(`  ✅ ${name}`);
  } else {
    console.log(`  ❌ ${name}${extra ? ' — ' + extra : ''}`);
    failures.push(name);
  }
}

console.log('\n[数据完整性]');
check('总章数 5000', D.total_chapters === 5000);
check('108 阶', D.world.levels.length === 108, `实际 ${D.world.levels.length}`);
check('4 界', D.world.realms.length === 4, `实际 ${D.world.realms.length}`);
check('实体 ≥ 6', D.canon.entities.length >= 6);
check('事实 ≥ 30', D.canon.facts.length >= 30);
check('伏笔 ≥ 5', D.canon.foreshadows.length >= 5);
check('探测章 ≥ 10', D.probes.length >= 10);

console.log('\n[章号 → 境界 映射正确性]');
const probes = [
  [1, '人界', '炼气初期'],
  [21, '人界', '炼气初期'],
  [22, '人界', '炼气中期'],
  [1601, '灵界', '灵徒初期'],
  [3001, '仙界', '散仙初期'],
  [4201, '神界', '神人初期'],
  [5000, '神界', '神主后期'],
];
for (const [ch, rm, nm] of probes) {
  const lv = levelAt(ch);
  const r = realmAt(ch);
  check(`第${ch}章 = ${rm}·${nm}`,
        lv.name === nm && r.name === rm,
        `实际 ${r.name}·${lv.name}`);
}

console.log('\n[章号覆盖无缝]');
let gap = null;
const lvls = D.world.levels;
for (let i = 0; i < lvls.length - 1; i++) {
  if (lvls[i + 1].s !== lvls[i].e + 1) {
    gap = `${lvls[i].name} 结束于 ${lvls[i].e}，${lvls[i+1].name} 开始于 ${lvls[i+1].s}`;
    break;
  }
}
check('108 阶无缝覆盖 1~5000', gap === null, gap);
check('首阶从 1 开始', lvls[0].s === 1);
check('末阶到 5000 结束', lvls[lvls.length - 1].e === 5000);

console.log('\n[战力单调 + 界内 rank 重置]');
let mono = true, monoAt = null;
for (let i = 0; i < lvls.length - 1; i++) {
  if (lvls[i + 1].power < lvls[i].power) {
    mono = false;
    monoAt = `${lvls[i].name}(${lvls[i].power}) → ${lvls[i+1].name}(${lvls[i+1].power})`;
    break;
  }
}
check('绝对战力全书单调递增', mono, monoAt);

let rankReset = true, rankAt = null;
const realms = D.world.realms;
for (let i = 1; i < realms.length; i++) {
  const first = lvls.find(l => l.realm === realms[i].name);
  const prevLast = [...lvls].filter(l => l.realm === realms[i-1].name).pop();
  if (!first || !prevLast) continue;
  if (first.rank >= prevLast.rank) {
    rankReset = false;
    rankAt = `${first.name}.rank=${first.rank} 未低于 ${prevLast.name}.rank=${prevLast.rank}`;
    break;
  }
}
check('界内 rank 每界重置（防数字爆炸）', rankReset, rankAt);

console.log('\n[上下文恒定：核心不变量]');
const sizes = D.probes.map(p => p.inject_chars);
const lo = Math.min(...sizes), hi = Math.max(...sizes);
const drift = (hi - lo) / lo;
console.log(`  注入块：${lo} ~ ${hi} 字符，漂移 ${(drift*100).toFixed(1)}%`);
check('漂移 < 30%（第5000章成本≈第1章）', drift < 0.30,
      `实际 ${(drift*100).toFixed(1)}%`);

console.log('\n[渲染函数可执行]');
try {
  for (const ch of [1, 21, 500, 1601, 2100, 2500, 3001, 4201, 4953, 5000]) {
    q('#scrub').value = String(ch);
    update();
  }
  check('10 个章节全部渲染成功', true);
} catch (e) {
  check('渲染函数执行', false, e.message);
}

console.log('\n[人物体系]');
check('cast 数据存在', Array.isArray(D.cast) && D.cast.length >= 8,
      '实际 ' + (D.cast ? D.cast.length : 0));
const mainChar = (D.cast || []).find(c => c.id === 'c1');
check('主角存在', !!mainChar);
check('主角里程碑 108 个', mainChar && mainChar.milestones.length === 108,
      '实际 ' + (mainChar ? mainChar.milestones.length : 0));
check('主角终点=神主后期',
      mainChar && mainChar.milestones[mainChar.milestones.length-1].level === '神主后期');
const voices = (D.cast || []).map(c => (c.voice||{})['语气'] + '|'
                  + ((c.voice||{})['口头禅']||[]).join(','));
check('声纹两两不同', new Set(voices).size === voices.length,
      '重复 ' + (voices.length - new Set(voices).size) + ' 个');
check('每个角色都有口头禅',
      (D.cast||[]).every(c => ((c.voice||{})['口头禅']||[]).length > 0));

console.log('\n[渲染输出非空]');
q('#scrub').value = '2100';
update();
check('注入块已渲染', q('#inject').innerHTML.length > 500,
      `${q('#inject').innerHTML.length} 字符`);
check('甘特图已渲染', q('#gantt').innerHTML.includes('gantt-bar'));
check('伏笔表已渲染', q('#fsTable tbody').innerHTML.includes('<tr>'));
check('大纲梯已渲染', q('#ladder').innerHTML.includes('第 2100 章'));
check('预算条已渲染', q('#budget').innerHTML.includes('width:'));
check('人物卡已渲染', q('#castGrid').innerHTML.includes('cast-card'));
check('大纲树已渲染', q('#outlineTree').innerHTML.includes('ol-node'));
check('章纲已渲染', q('#chOutline').innerHTML.includes('beat-item'));


console.log('\n[关键演示点：同一实体不同章节状态不同]');
const p2200 = D.probes.find(p => p.chapter === 2100);
const p2500 = D.probes.find(p => p.chapter === 2500);
if (p2200 && p2500) {
  check('第2100章 右臂=断',
        (p2200.state_c1['右臂'] || '').includes('断'));
  check('第2500章 右臂=已愈',
        (p2500.state_c1['右臂'] || '').includes('已愈'));
} else {
  check('找到 2100/2500 探测点', false);
}

console.log('\n[伏笔状态随章号变化]');
const fsCh100 = D.canon.foreshadows.map(f => ({
  id: f.id, planted: f.planted,
  st: 100 > f.hi ? 'overdue' : (100 >= f.lo ? 'due'
      : (100 >= f.planted ? 'planted' : 'unplanted')),
}));
check('第100章时 f1 尚未埋（f1 埋于第100章，边界）',
      fsCh100.find(x => x.id === 'f1').st === 'planted');
check('第100章时 f2 未埋',
      fsCh100.find(x => x.id === 'f2').st === 'unplanted');

console.log('\n' + '='.repeat(56));
if (failures.length) {
  console.log(`❌ ${failures.length} 项失败：`);
  failures.forEach(f => console.log('   · ' + f));
  process.exit(1);
}
console.log('✅ 全部断言通过 —— 大屏逻辑正确');
process.exit(0);
