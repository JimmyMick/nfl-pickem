---
title: New stuff — 🟡 preview rows, 🎯 dogs, and the Super Bowl calculator
author: Jim
date: 2026-09-07 20:43
---

Couple of new visual cues showed up on the **Weekly Preview** tab this week. Both
are there to answer the same question faster: *where does the model disagree with
Vegas, and is it a spot worth a look?* Here's how to read them.

## 🟡 A tinted row = the model likes the underdog

When a game's row is shaded light amber, it means **the model's pick is the team
Vegas has as the underdog.** In other words, the model and the market are on
opposite sides of the game — the model gives a dog better than a 50% shot to win
outright.

That's it. No tint = the model and Vegas agree on who's better (they just might
argue about *how much*). Tint = a genuine disagreement, with the model taking the
points-getter.

A few honest reminders about those yellow rows, because we actually checked:

- **A disagreement is not a prediction you should trust blindly.** Last season,
  when the model liked the market dog straight-up, those picks went **basically
  50/50** — a coin flip. The model was even a touch *overconfident* there.
- **The further from 50%, the more skeptical you should be**, not less. The
  model's loudest dog barks were some of its worst misses.
- **Check the driver.** If the reason is "Elo" (our slow, season-long power
  rating), fade it — the market usually already knows the newer news. Disagreements
  driven by recent **EPA** (efficiency) held up better.

So treat a yellow row as *"huh, worth a second look,"* not *"back up the truck."*

## 🎯 A target in the Spread column = a short dog the model also likes

Right next to each game is the underdog's **spread** — the points they're getting.
When you see a **🎯**, it means two things are true at once:

1. the **model leans that underdog**, and
2. the spread is **short** (3 points or fewer).

That combo is the interesting one. Here's why we flag it specifically: betting
these dogs to win *outright* (the moneyline) is roughly a wash. But **taking the
points** on the same games has been the steadier way to ride them — in a
2016–2025 backtest, the model's disagreement dogs covered about **57%** against
the spread, with far less week-to-week whiplash than the moneyline version. When
the number is small, that hook does a lot of work: it turns the model's near-miss
coin-flips into covers, while the blowout misses were going to lose either way.

So a **🎯** is shorthand for *"if you were ever going to take a dog the model
likes, this is the cleaner way to do it — grab the points."*

## 🏆 The Super Bowl calculator (Playoff odds tab)

New toy: head to the **🏆 Playoff odds** tab and you'll see every team's shot at
the playoffs, the division, the #1 seed, the conference, and the Super Bowl. Under
the hood it's a **Monte Carlo** — the model plays out the entire rest of the
season *thousands of times* and counts how often each team ends up hoisting the
trophy. It refreshes every Tuesday, so you can watch a team's number climb or
crater week to week.

Here's the fun wrinkle. Some of you noticed our model had, say, the **Seahawks
over the Rams** for the Super Bowl while Kalshi and the sportsbooks have the **Rams
#1 overall.** Who's right? Bit of both — and now you can see it either way:

- **Pure model** — our own ratings, which are *backward-looking.* They lean heavily
  on what teams actually did last season and only slowly forget it. Great signal,
  but at Week 1 they haven't fully "seen" the offseason — the free-agent hauls, the
  draft, a healthier quarterback, a new coordinator.
- **Market-anchored** — flip this toggle and we blend our ratings toward what the
  **betting market** thinks, reverse-engineered from the point spreads. The market
  prices all that forward-looking offseason stuff, so teams that got better over
  the summer (hi, Rams) climb toward where Vegas has them.

Neither is "the truth." The pure model is our honest read off the field; the
market view is the crowd's forward-looking wisdom. Watching them **disagree** is
half the fun — and as real games get played, our backward-looking ratings catch up
and the two views drift together.

## The fine print (you knew it was coming)

None of this is a betting tip, and the app isn't a sportsbook. Even the spread
angle **hasn't cleared our statistical bar** — it looks steadier, but a proper
significance test still can't rule out plain luck. That's exactly why we're
tracking both the moneyline and the spread versions **live, going forward**, over
on the **📈 Paper Play** tab. If the 🎯 approach is real, it'll show up there over
a season of games nobody's seen yet. If it face-plants, that's a useful answer too.

Read the colors, enjoy the arguments with the model, and — as always — **don't bet
your rent.** 🧽
