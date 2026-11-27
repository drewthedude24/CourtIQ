# Fatigue: what changes as a session goes on

Measured 2026-11-27 on clips `s1` to `s5` with the detector on `main`. The five clips are one
outing of about 9 minutes, filmed back to back. 49 of the 50 labeled shots are used (the
detector does not find the shot at 8.8 s in `s4`).

The comparison was run with throwaway scripts (scikit-learn and statsmodels in a separate
environment). They are not in the repo. The model the app uses is `backend/fatigue.py`, and
uploading the five clips into one account reproduces its numbers.

## The question, with no fatigue label

The clips are labeled make or miss. Nothing says how tired the shooter was. So the target is
**where a shot is in its session**: if a form number follows shot order, it is a candidate
sign of tiring. Each clip counts as one session.

Two terms used below:

- **Leave-one-session-out cross-validation**: fit on four sessions, test on the fifth, and
  repeat so each session is the test once. Shots from one session are never in both.
- **Overfitting**: a model that memorises its training shots. It looks good on them and bad
  on new ones, so its training error is much lower than its test error.

## What changes inside a session

Change from the first shot to the last, from a model that gives each session its own level
(a mixed model with a random intercept per session).

| Number | First to last | 95% range | p | Sessions lower at the end |
|---|---|---|---|---|
| **Jump (shoulder-heights)** | **-0.033** | **-0.051 to -0.016** | **<0.001** | **5 of 5** |
| Knee bend (°) | -0.9 | -5.8 to +3.9 | 0.70 | 3 of 5 |
| Elbow bend (°) | +0.3 | -3.6 to +4.2 | 0.88 | 2 of 5 |
| Arm angle (°) | +1.4 | -0.6 to +3.4 | 0.18 | 1 of 5 |
| Flight time (s) | +0.011 | -0.034 to +0.056 | 0.63 | 3 of 5 |

Only the jump moves. It drops about 12% of its average (0.266). Seven numbers were tested
(the five above plus two timing numbers), and the jump result still holds after allowing
for that (0.05 / 7 = 0.007).

### Checks that it is not an artifact

- **Camera distance**: the shooter's height in pixels does not change through a session (p 0.85).
- **Where he stands**: the feet's position against the rim does not change (p 0.69).
- **Rest**: shots come about 1.9 s closer together late in a clip. With rest time held
  fixed the jump still drops (-0.025, p 0.03).
- **One odd session**: the first-to-last drop fitted without each session in turn stays
  between -0.029 and -0.036.

### It comes back after a break

The iPhone stores when each recording started. The breaks between clips were 24, 34, 77 and
30 s. Inside a clip a shot comes about every 8 s.

- Per shot inside a clip: -0.0035 (p 0.0007).
- Per shot across the whole outing: -0.0003 (p 0.25).

So the jump is highest on the first shot after a break, falls over the next few shots, and
there is no slow decline across the 9 minutes.

## Models compared

All tested by leave-one-session-out. Error is the average miss.

**Guess where in the session a shot is (0 first, 1 last) from its form:**

| Model | Train error | Test error |
|---|---|---|
| Always guess the middle | 0.274 | 0.275 |
| Line on jump only | 0.244 | 0.242 |
| Ridge regression, five numbers | 0.237 | 0.255 |
| Decision tree, five numbers | 0.192 | 0.278 |
| Random forest, five numbers | 0.196 | 0.268 |

**Guess the jump on each shot (shoulder-heights):**

| Model | Train error | Test error |
|---|---|---|
| Always the average | 0.0177 | 0.0181 |
| Line per shot in the session | 0.0165 | 0.0175 |
| Tiredness that builds up and fades with rest | 0.0155 | 0.0167 |

The line was chosen. The rest model is better in only 3 of 5 sessions and needs one more
setting (how fast tiredness fades, which came out at 7 to 15 s).

## Overfit or underfit

- **Jump line: not overfit.** Train and test error are almost the same, and its one learned
  number barely moves when a session is left out.
- **Trees and the five-number models: overfit.** They beat the baseline on training shots and
  lose to it, or to the jump-only line, on new ones.
- **Is 50 shots enough?** Enough to see the jump drop. Not enough for models with several
  inputs, or for anything about makes and misses.
- **The line leaves most of the wobble unexplained.** A jump changes by about 0.023 from shot
  to shot for other reasons, and the whole drop over a session is 0.033.

## Makes and misses

- Form does not predict a make on a new session: logistic regression on the five numbers
  scores a test AUC of 0.48 to 0.51 (0.5 is a coin flip), against 0.69 to 0.73 on training.
- Jump is the same on makes and misses (difference -0.001).
- Makes by clip: 70%, 67%, 55%, 56%, 50%. First half of a session 70% (16 of 23), second half
  50% (13 of 26). The trend has p 0.20, so it can be luck.
- **Arc height** (how high the ball goes above the rim, divided by body height) is not one of
  the app's numbers yet. Makes by arc: lowest third 41%, middle 56%, highest 81%. On a
  left-out session it ranks makes above misses with AUC 0.63, but its probabilities are no
  better than the base rate. Worth measuring on more shots before it is used.

## What other studies found

- Jump height is the most consistent thing to drop with fatigue. Release angle and speed
  stayed the same ([St. Michel et al. 1995](https://ojs.ub.uni-konstanz.de/cpa/article/view/2931)).
- About 100 s of repeated sprints changed nothing in elite under-18 players
  ([Slawinski et al. 2018](https://pmc.ncbi.nlm.nih.gov/articles/PMC6006537)).
- A 12-minute game simulation lowered the entry angle and accuracy
  ([Bourdas et al. 2024](https://pmc.ncbi.nlm.nih.gov/articles/PMC10974731)).
- Splitting test data by shot and not by session makes a model look far better than it is
  ([Saeb et al. 2017](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5441397/)).

Every study that found an effect used hard running or cycling. Ten unhurried shots in 80 s
is far less work, so the page reports a **jump drop**. It does not claim to measure fatigue.

## What the app does

`backend/fatigue.py` fits, for one user:

    jump on a shot = that session's starting jump + per_shot * (shots taken before it)

It is refitted from all of that user's shots on every request (`GET /api/stats/fatigue`), so
a new session updates it. It needs three sessions with at least five measured jumps each.
Every time, it also runs the leave-one-session-out check and reports both errors, so the page
can say whether the trend holds up for that user.

On the five clips uploaded into one local account (the app numbers shots as the detector
finds them):

| | |
|---|---|
| Change per shot | -0.0037 |
| First shot to tenth | -12% |
| Sessions that ended lower than they started | 5 of 5 |
| Error on a left-out session, with the trend | 0.0154 |
| Error on a left-out session, without it | 0.0173 |

## Limits

- One shooter, one outing, one court. Nothing here says the pattern holds for anyone else.
- The line assumes every shot costs the same. The data hints that the drop happens in the
  first four or five shots and then levels off.
- The app treats each upload as its own session, starting fresh. It does not know how long
  the break before it was.
