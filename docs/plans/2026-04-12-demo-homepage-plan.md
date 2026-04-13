# BridgeSpace Demo Homepage Plan

## Goal

Replace the current single-scroll demo homepage with a game-like multi-page presentation hub that lets the presenter switch between major BridgeSpace flows:

1. Lobby / overview
2. SmartGate registration and recognition
3. Zone selection and queue logic
4. SmartCount people-detection demo
5. Live monitoring dashboard

## Design Direction

- Visual tone: control-room / game mission hub rather than corporate dashboard
- Navigation: persistent side menu with page switching
- Storytelling: each page explains one stage of the visitor journey and provides only the actions relevant to that stage
- Continuity: the same live backend state is shared across all pages so the presenter can move between pages without losing context

## Information Architecture

### Lobby
- Present the overall BridgeSpace concept
- Show the full mission flow in six steps
- Provide quick links to API docs and the monitoring page

### SmartGate
- Explain first-time registration vs returning-user face scan
- Provide actions for demo visitor registration
- Show the currently registered demo user and SmartGate command block

### Zone Select
- Let the presenter choose a target zone
- Provide actions to force walk-in mode or queue mode
- Let the presenter join the zone and start a session

### SmartCount
- Show a visual people-detection arena
- Provide push and autoplay occupancy simulation
- Explain how SmartCount feeds `/zones/occupancy`

### Monitoring
- Show live occupancy, sessions, queue, devices, and alerts
- Preserve the existing monitoring components

## Implementation Notes

- Keep a single React app and switch pages via hash or local state
- Preserve the WebSocket and REST data model from the current App
- Reuse existing panels:
  - `OccupancyBoard`
  - `QueueBoard`
  - `SessionPanel`
  - `DevicePanel`
  - `AlertBanner`
  - `CalledAlert`
- Keep `#dashboard` as a focused full-screen monitoring mode

## Verification

- `npm run build`
- Local dev preview with backend connected
- Visual smoke test confirming:
  - page switching works
  - demo actions still hit backend
  - monitoring page still reflects live state
