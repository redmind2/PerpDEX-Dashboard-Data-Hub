# Codex Start Prompt - PerpDEX Dashboard / Data Hub

너는 `PerpDEX Dashboard / Data Hub` 프로젝트를 담당한다.

## 목표
PerpDEX public market data를 수집하고, 저장하고, CLI/웹 대시보드에서 보여주는 공용 데이터 허브를 만든다. 이 프로젝트는 나중에 Pagu.info, PerpDEX Farming Bot, Cross Exchange Trading Bot이 같이 사용할 수 있는 데이터 계층이 된다.

## 코드 레포
- 새 레포: `C:\Users\USER\Documents\PerpDEX-Dashboard-Data-Hub`
- 이전 구현 참고 레포: `C:\Users\USER\Documents\PerpDEX 파밍봇`
- 이전 DB 참고: `C:\Users\USER\Documents\PerpDEX 파밍봇\data\perpdex_phase1.sqlite`

## Obsidian HQ
- `C:\Users\USER\Desktop\Pagu's Works\06-Coding\PerpDEX Dashboard Data Hub`

## 현재까지 검증된 이전 구현
- Hibachi public collector: BTC-PERP, ETH-PERP, EUR-PERP
- Rise public collector: BTC-PERP mapped to BTC/USDC, market_id 후보 1
- CLI: `overview`, `status`, `storage`, `prune`, `collect-live`
- PM2 collector config existed in previous repo
- Phase 2E에서 PM2 online + overview OK까지 확인함
- 현재 로컬 컴퓨터에서는 장기 DB 적재하지 않기로 했고 collector는 꺼둔 상태

## 절대 범위 밖
- wallet 연결 금지
- private key/API key/signature/session key 금지
- balance/position/order/cancel 기능 금지
- 거래 실행 금지

## 다음 작업 요청
1. 이전 `PerpDEX 파밍봇` 레포의 public data collector/dashboard 구현을 새 `PerpDEX-Dashboard-Data-Hub` 레포로 옮기는 migration plan을 세워라.
2. `data/`의 SQLite 실데이터와 로그는 복사하지 말고, 코드/설정/테스트/문서만 옮기는 방향으로 계획하라.
3. 외부 DB(PostgreSQL/TimescaleDB 등)로 확장 가능한 구조를 제안하되, 우선은 local SQLite 호환을 유지하라.
4. 초보자가 이해할 수 있게 파일 역할과 실행 명령을 쉽게 설명하라.