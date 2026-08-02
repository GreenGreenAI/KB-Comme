/** What the browser remembers between one page load and the next.
 *
 *  The server is stateless on purpose — the browser holds what has been said
 *  and resends it. That was true and also fragile: the browser held it in
 *  memory only, so a refresh threw away every fact the company had typed. With
 *  sign-in closed there is no account to fall back on, and the questions the
 *  rules ask are not the kind anyone wants to answer twice.
 *
 *  **`sessionStorage`, not `localStorage`.** What is kept here is a company's
 *  trade: amounts, settlement dates, its size, whether it has credit issues,
 *  its K-SURE grade. On the company's own machine keeping that for weeks would
 *  be convenient; on a shared one it is a leak that outlives the visit, and
 *  without accounts nothing here can tell which machine this is. So it lives
 *  as long as the tab does — which covers the refresh this exists for — and
 *  closing the tab is the erase.
 *
 *  Nothing is sent anywhere. This is the same data the page already holds,
 *  written where a reload can find it.
 */

const KEY = "tradeflow.session";

/** Bumped when the stored shape changes.
 *
 *  A payload written by an older build is dropped rather than migrated: the
 *  cost of guessing wrong is a screen rendering a conversation that half
 *  matches the code, and the cost of dropping is one re-typed question. */
const VERSION = 3;

/** How many turns are kept. Each result carries a full decision packet, and
 *  `sessionStorage` gives roughly five megabytes — a long conversation would
 *  otherwise fail to write at all, silently, which is the failure mode this
 *  module exists to remove. The oldest go first; the facts are kept whole
 *  either way, so nothing the rules read is lost by trimming the thread. */
const KEEP_TURNS = 40;

export function load() {
  let raw;
  try {
    raw = window.sessionStorage.getItem(KEY);
  } catch {
    // Private modes and locked-down browsers throw on access rather than
    // returning null. Nothing here is worth an error page.
    return null;
  }
  if (!raw) return null;
  try {
    const stored = JSON.parse(raw);
    if (stored?.v !== VERSION) return null;
    return {
      ...stored.state,
      // Read once already. The cascade must not replay on a refresh.
      turns: (stored.state.turns ?? []).map((turn) => ({ ...turn, restored: true })),
    };
  } catch {
    return null;
  }
}

export function save(state) {
  const turns = state.turns ?? [];
  const payload = {
    v: VERSION,
    state: { ...state, turns: turns.slice(-KEEP_TURNS) },
  };
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(payload));
  } catch {
    // Over quota, or storage refused. Losing the memory is survivable; losing
    // the turn the user is in the middle of is not, so this never throws.
  }
}

export function forget() {
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    /* nothing to do about it, and nothing depends on it */
  }
}
