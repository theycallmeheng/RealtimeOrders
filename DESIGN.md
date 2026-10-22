# RealtimeOrders design direction

Vietnamese responsive product UI. A daily stock list is the customer's main
screen; an order processing table is the administrator's main screen.

- White #ffffff, page background #f7f8fa, text #17252a, muted #64748b,
  border #dbe2e8, primary accent #0f766e.
- Use the system sans stack with Vietnamese support. Body 14–16px;
  descriptive headings 20–28px. Do not invent decorative marketing sections.
- Buttons/inputs radius 6px; grouped panels 8px. Prefer rows and separators
  to repeated cards; shadows reserved for menus and dialogs.
- Font Awesome icons improve recognition only; keep text on important actions.
- Desktop stock table and compact mobile list share one data model. Each row
  shows name, unit, price for this customer, remaining quantity and order action.
- Distinguish “còn trong kho”, “đang chờ duyệt” and “đã được duyệt”. Never imply
  that submitting an order reserves stock.
- Mobile target width 360px; touch controls at least 44px; visible keyboard
  focus, readable errors, and status distinguished by text as well as color.
- Show pending submission, reconnecting and last update states near the content.
  Keep form input during transient failure; disable duplicate submission.
- A stale price or shipping fee requires a fresh confirmation with visible
  differences. Do not silently change the total.
- Do not use gradients, glass effects, large centered heroes, decorative badges
  or a promotional dashboard as the signed-in shopping interface.
