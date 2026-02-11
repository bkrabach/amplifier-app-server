# Attention Firewall Rules

## User Identity
- **Name**: Brian Krabach
- **Aliases**: bkrabach, Brian, BK

## VIP Senders (Always Push)
- Kevin Scott
- Sam Schillace
- Charlie Krabach (wife)
- Dan Shapiro
- Jesse Vincent
- Justin (StrongDM - hosting event tomorrow in Palo Alto)
- Family members

## App-Specific Rules

### CRITICAL: Ignore ntfy (Prevents Loop)
- **ALWAYS SUPPRESS**: Any notification where the sender/source is "ntfy"
- These are OUR OWN outbound notifications being reflected back via Phone Link
- Do NOT evaluate, do NOT score, do NOT re-push - just ignore completely

### Phone Link / SMS
- **Push**: ALL messages from Charlie Krabach (wife), EXCEPT videos to watch
- **Push**: Family members, unknown numbers (might be important)
- **Summarize**: Friend messages
- **Suppress**: Marketing SMS, verification codes (unless time-sensitive)

### WhatsApp
- **Push**: ALL messages related to Palo Alto trip/meetings
- **Push**: Messages from Dan Shapiro, Jesse Vincent, Sam Schillace, Justin (StrongDM)
- **Push**: Direct messages, trip coordination, meeting logistics
- **Push**: StrongDM event details and coordination
- **Summarize**: General group chatter not related to Palo Alto
- **Suppress**: After-hours social chat unless trip-related

### Outlook
- **Push**: ONLY critical/urgent items (P0/P1, outages, emergency decisions)
- **Summarize**: Regular work email
- **Suppress**: Marketing, automated reports, non-urgent updates

### Teams
- **Push**: ONLY critical items (outages, P0/P1 issues, emergency @mentions)
- **Push**: Channel keywords: "outage", "down", "P0", "P1", "critical"
- **Summarize**: Regular direct messages, @mentions
- **Suppress**: Channel chatter, reactions, non-urgent bot messages

### Slack
- **Push**: ONLY critical direct messages or @mentions
- **Summarize**: Regular channel activity
- **Suppress**: Bot notifications

## Time-Based Rules
- **Before 8am**: Only emergencies and family
- **8am-6pm**: Normal rules apply (modified by current context below)
- **After 6pm**: Family priority, work can wait unless critical emergency
- **Weekends**: Family only, suppress work unless critical emergency

## Keyword Triggers (Always Elevate Priority)
- "urgent", "ASAP", "emergency"
- "deadline", "due today", "EOD"
- "blocking", "outage", "down"
- "decision needed", "approval required"
- "P0", "P1", "critical issue"

## Current Context (Time-Sensitive Instructions)

### 🛫 ACTIVE: Palo Alto Trip (Feb 3-6, 2026)
**Status**: Traveling to Palo Alto - boarding flight now, returning Thursday ~noon

**Push Immediately:**
- ALL SMS/Phone Link from Charlie Krabach (wife) - EXCEPT videos
- ALL WhatsApp messages related to Palo Alto trip/meetings
- Messages from: Dan Shapiro, Jesse Vincent, Sam Schillace, Justin (StrongDM)
- Trip logistics: flight changes, meeting times/locations, dinner plans
- StrongDM event coordination (Justin hosting tomorrow)
- Microsoft CRITICAL only: P0/P1, production outages, emergency decisions

**Summarize/Hold:**
- Regular work email and Teams messages
- Social WhatsApp group chat not related to Palo Alto
- Videos from Charlie (can watch later)
- Non-urgent Microsoft matters

**Suppress:**
- Marketing, newsletters, automated reports
- Minor bugs, test failures, dev environment issues
- Non-urgent work notifications

**Key People & Events in Palo Alto:**
- **Justin** (StrongDM) - Hosting event tomorrow (Feb 4)
- **Dan Shapiro** - Meeting coordination
- **Jesse Vincent** - Meeting coordination
- **Sam Schillace** - Meeting coordination
- Others TBD during trip

**Rationale**: Focus on trip coordination and family. Only interrupt for true work emergencies.

---

**After Feb 6, 2026 (post-trip):**
- Return to standard time-based and VIP rules
- Resume normal work notification filtering
- Clear this travel context section
