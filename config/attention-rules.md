# Attention Firewall Rules

## User Identity
- **Name**: Brian Krabach
- **Aliases**: bkrabach, Brian, BK

## VIP Senders (Always Push)
- Kevin Scott
- Sam Schillace
- Charlie Krabach
- Family members

## Focus Mode Rules
When in focus mode:
- Only push for VIPs or explicit @mentions
- Summarize everything else
- Suppress system notifications entirely

## App-Specific Rules

### Outlook
- **Push**: VIPs, "urgent" in subject, meeting changes for today
- **Summarize**: Regular email, newsletters
- **Suppress**: Marketing, automated reports

### Teams
- **Push**: Direct messages, @mentions, channel keywords: "launch", "outage", "regression"
- **Summarize**: Channel chatter, reactions
- **Suppress**: Bot messages unless actionable

### Phone Link
- **Push**: Family members, unknown numbers (might be important)
- **Summarize**: Friend messages
- **Suppress**: Marketing SMS, verification codes (unless time-sensitive)

### Slack
- **Push**: Direct messages, @mentions
- **Summarize**: Channel activity
- **Suppress**: Bot notifications

## Time-Based Rules
- **Before 8am**: Only push emergencies and family
- **8am-6pm**: Normal rules apply
- **After 6pm**: Family priority, work can wait unless urgent
- **Weekends**: Family only, suppress work unless emergency

## Keyword Triggers (Always Elevate Priority)
- "urgent", "ASAP", "emergency"
- "deadline", "due today", "EOD"
- "blocking", "outage", "down"
- "decision needed", "approval required"
- "bug", "crash", "error", "exception", "failure"
- "regression", "broken", "not working"
- "critical issue", "P0", "P1"

## Current Context (Time-Sensitive Instructions)

**Before 12:00 PM (noon):**
- **HIGH ALERT for bugs** - Push for ANY bug report, no matter how minor
- Includes: bug mentions, errors, crashes, exceptions, test failures
- Rationale: In meetings, need to be aware of all issues being reported
- Push immediately for:
  - ANY bug reports or crash notifications (even minor)
  - P0/P1 issues
  - Production errors or regressions
  - VIP requests
  - Family messages

**After 12:00 PM (noon):**
- **Standard bug filtering** - Only push for IMPACTFUL bugs
- Push criteria: P0/P1, production issues, user-impacting crashes
- Summarize: Minor bugs, test failures, dev environment issues
- Rationale: Post-meetings, filter for what actually needs immediate attention
