# Receipt Templates

This folder can contain additional receipt templates or formatting helpers as the system expands.

Currently, all templates are in `printer.py` methods:
- `_print_reminder()`
- `_print_url_summary()`
- `_print_list()`
- `_print_question()`
- `_print_generic()`

As complexity grows, these can be moved to separate template files and use Jinja2 or similar for more flexible formatting.

## Future Structure

```
templates/
  reminder.txt       ← Jinja2 template for reminders
  url.txt            ← Template for URL summaries
  list.txt           ← Template for checklists
  question.txt       ← Template for Q&A
  generic.txt        ← Fallback template
```

Each would be rendered with job context before sending to printer.
