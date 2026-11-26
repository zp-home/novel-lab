/* GitHub Pages 只读静态适配层：把 /api/* 映射到 ./data/* 快照 */
(function () {
  const realFetch = window.fetch.bind(window);
  function jsonResp(obj, status) {
    return new Response(JSON.stringify(obj), {
      status: status || 200,
      headers: { 'Content-Type': 'application/json; charset=utf-8' }
    });
  }
  window.fetch = async function (input, init) {
    const raw = typeof input === 'string' ? input : (input && input.url) || '';
    const url = raw.split('?')[0];
    if (url === '/api/projects') {
      return realFetch('./data/projects.json');
    }
    const mMan = url.match(/^\/api\/manifest\/([^/]+)$/);
    if (mMan) {
      return realFetch('./data/manifest_' + decodeURIComponent(mMan[1]) + '.json');
    }
    const mCh = url.match(/^\/api\/chapter\/([^/]+)\/(\d+)$/);
    if (mCh) {
      const r = await realFetch('./data/chapters/' + decodeURIComponent(mCh[1]) + '/' + mCh[2] + '.json');
      if (!r.ok) return jsonResp({ error: '该章尚未生成（静态快照模式）' }, 404);
      return r;
    }
    const mLog = url.match(/^\/api\/log\/([^/]+)$/);
    if (mLog) {
      const r = await realFetch('./data/logs_' + decodeURIComponent(mLog[1]) + '.json');
      if (!r.ok) return jsonResp({ lines: [] }, 200);
      return r;
    }
    if (url === '/api/run' || url === '/api/stop') {
      return jsonResp({ error: '当前为 GitHub Pages 只读静态展示版，启停任务请在本地运行 python web/server.py' }, 400);
    }
    return realFetch(input, init);
  };
})();
