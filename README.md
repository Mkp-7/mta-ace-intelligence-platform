# MTA Rider Intelligence Platform

> AI-powered rider intelligence for Transit Operations - turning raw App Store feedback into executive-ready insights automatically.

## Overview

A 4-module analytics platform that ingests real rider review data from the MTA app and delivers continuous, automated insights for Transit Operations leaders. What traditionally takes an analyst 3 days to produce manually - theme analysis, anomaly detection, executive summaries - this platform produces in under 30 seconds.

## What It Does

**Voice of Customer AI**
Reads thousands of rider reviews and automatically identifies recurring themes (real-time tracking accuracy, service alerts, trip planning, etc.), flags sudden rating drops, and generates polished executive summaries ready for leadership - no manual effort required.

**Service Pulse**
Tracks how rider sentiment evolves over time, pinpointing exactly which app release caused a rating shift. Gives operations leaders a clear before/after view of every change.

**Test & Learn Autopilot**
Uploads pilot vs control data and instantly computes statistical significance, effect size, and a clear verdict - scale it, kill it, or keep watching. Eliminates the need to wait for monthly manual reads.

**Analyst Copilot**
A plain-English chat interface where any leader can ask questions about rider sentiment and get answers backed by real data - without routing requests through the analytics team.

## Built With

Python · Streamlit · Plotly · Groq LLM · SciPy · Pandas · GitHub Actions

## Data Source

Reviews are pulled automatically from the Apple App Store listing for **The Official MTA App** (`apps.apple.com/us/app/the-official-mta-app/id1297605670`) via the GitHub Actions scraper, which runs on every push to `config.py`.

---

*Configured for the MTA. The platform is designed to work across any brand or agency by editing `config.py`.*
