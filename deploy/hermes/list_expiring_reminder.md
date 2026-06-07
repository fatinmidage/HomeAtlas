# Hermes Scheduled Reminder

Use this after `home_atlas` is configured as an MCP server in Hermes.

Suggested schedule:

```text
Every day at 9:00, call the HomeAtlas MCP tool `home_atlas` with:

哪些物品 14 天内临期或待续费？

Then summarize the result in Chinese. Include item name, location, expiry_date or renewal_date when present. If there are no matching items, say "未来 14 天没有临期或待续费物品。"
```

Weekly alternative:

```text
Every Sunday at 20:00, call the HomeAtlas MCP tool `home_atlas` with:

哪些物品 30 天内临期或待续费？

Send the reminder to me.
```

Verification sample:

```text
Call `home_atlas` once with: 哪些物品 30 天内临期或待续费？
```
