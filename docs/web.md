# C3 — Web chat UI

Owner: Nour

## What it is

`app/web/index.html` is the visible product: one self-contained page with no build step and no
dependencies. It renders what A2 sends and posts back every action the user takes. It holds no
business logic and no Azure knowledge.

Open it with `?mock` in the URL and it runs a scripted conversation with no server at all, which
is how it is developed and demoed before A2's endpoints are wired into `main.py`.

## What it renders

| Response type | Rendering |
| --- | --- |
| `question` | Assistant bubble with an accent bar |
| `info` | Plain assistant bubble |
| `plan` | Card: table of `Create`/`Modify`/`Delete`, estimated cost, warnings, Confirm and Cancel |
| `cost_warning` | Amber card with "I accept the cost" and Cancel |
| `status` | Card: state badge, message, `deployment_id`, "View run in Azure DevOps" when `link` is present, outputs table |
| `error` | Red bubble, and a banner if the HTTP call itself fails |

## Behaviour you should be able to explain

- **Confirm is bound to a `plan_id`.** The button sends `{session_id, plan_id, approve: true,
  accept_cost: false}`. Confirm can never accept an over-budget plan by itself.
- **`accept_cost: true` comes only from the cost card.** That card appears when A2 returns
  `cost_warning`, and it reuses the `plan_id` of the plan on screen.
- **Both buttons disable on the first click**, before the request leaves the page. A2 also
  refuses a double confirmation; the UI does not rely on it.
- **A new plan supersedes the old card.** The previous card greys out, its buttons disable, and it
  is labelled "Superseded by a newer plan". This mirrors the rule that a new message invalidates
  the current plan.
- **Polling** calls `GET /status/{session_id}` every 2 seconds, updates the status card in place,
  and stops on `succeeded`, `failed`, or after 5 minutes.
- **Secrets are shown once.** Any output whose name matches `password`, `secret`, `accountkey` or
  `connectionstring` is masked, with Show, Hide and Copy. Copy falls back to revealing the value
  when the clipboard API is unavailable (plain `file://`).
- **All text goes through `textContent`.** Nothing from the model or from Azure is ever parsed as
  HTML.

## Accessibility and layout

- The log is `aria-live="polite"`, errors use `role="alert"`.
- The input has a real label (visually hidden), the form submits on Enter, and the page is
  keyboard-navigable. New plan and cost cards take focus so screen-reader and keyboard users land
  on the new content.
- Tables scroll horizontally inside their card instead of breaking the layout, and messages go
  full width under 560 px.

## How to test

Without a server:
