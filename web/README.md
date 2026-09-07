# NewsTrace web

Vue 3 + TypeScript 프론트엔드다. 브라우저는 HTTP/SSE API만 호출하며 MS-SQL, MCP, LLM에
직접 접근하지 않는다.

```bash
cp .env.example .env
npm ci
npm run dev
```

`VITE_API_BASE_URL`의 기본값은 `http://localhost:8000`이다. 저장소 루트에서는
`make web-install`, `make web`, `make web-check`를 사용한다.
