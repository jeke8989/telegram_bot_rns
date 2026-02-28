/**
 * Centralized API client with auth handling.
 * Usage: await api.get('/api/users'), await api.post('/api/clients', { name: 'Test' })
 */
const api = (function () {
    async function request(url, opts = {}) {
        const res = await fetch(url, {
            headers: { 'Content-Type': 'application/json', ...opts.headers },
            ...opts,
        });
        if (res.status === 401) {
            window.location.href = '/login';
            throw new Error('unauthorized');
        }
        return res;
    }

    return {
        get(url)           { return request(url); },
        post(url, body)    { return request(url, { method: 'POST',   body: JSON.stringify(body) }); },
        patch(url, body)   { return request(url, { method: 'PATCH',  body: JSON.stringify(body) }); },
        put(url, body)     { return request(url, { method: 'PUT',    body: JSON.stringify(body) }); },
        del(url)           { return request(url, { method: 'DELETE' }); },
        /** Raw request for FormData uploads etc. */
        raw(url, opts)     { return request(url, opts); },
    };
})();
