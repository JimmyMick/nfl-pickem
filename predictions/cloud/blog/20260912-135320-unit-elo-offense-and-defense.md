---
title: New tab — ⚔️ Unit Elo (splitting a team into offense and defense)
author: Jim
date: 2026-09-12 13:53
---

You know the model already keeps a single **Elo** number for each team — one
rating that says how good they are overall. New tab up top, **⚔️ Unit Elo**,
takes that idea and splits it in two: a rating for the **offense** (how many
points a team scores) and a separate rating for the **defense** (how few it lets
up). Same Elo machinery, just pointed at each side of the ball.

## How to read it

Both ratings sit on the familiar Elo scale where **1500 = perfectly average**.
Above 1500 is better than average, below is worse — and yes, for defense "better"
means *stingier* (gives up fewer points).

The headline is the **scatter plot**: every team is a dot, offense along the
bottom, defense up the side, with dashed lines marking league-average. That
carves the league into four corners:

- **Top-right** — good at *both*. The scary teams. (Seattle's parked up here —
  top-shelf offense *and* the league's best defense, which is exactly why their
  overall rating leads the pack.)
- **Bottom-left** — bad at both. The rebuild zone.
- **Top-left** — great defense carrying a meh offense. Rock fights.
- **Bottom-right** — big offense, no defense. Shootout merchants — fun to watch,
  exhausting to root for.

Below the chart is the same thing as a **sortable table**. Click any column to
rank by it. The **"pts vs avg"** columns are the plain-English version: `+4.8`
means that offense scores about five more points a game than an average one;
a defense at `+1.4` gives up about a point and a half fewer than average.

## Why it's neat

It tells you *how* a team is good, not just *that* they're good. Two 10-win teams
can look totally different under the hood — one wins 31–28, the other wins 16–13
— and this tab shows it at a glance. It also updates as the season goes: a team
that lays an egg on offense (looking at you, Rams, held to 7 in Week 1) slides
left in real time.

## The fine print

This is built purely from **final scores**, which means field goals and any
return/defensive touchdowns get lumped into "offense" and "defense." So it's not
a *pure* offense-vs-defense split — **special teams** is quietly baked in. Giving
special teams its own rating is a fun next project, but it needs play-by-play
guts, so we shelved it for now.

Go poke around, sort the table, find out your team is a "shootout merchant," and
argue about it. 🧽
