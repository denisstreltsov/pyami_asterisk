# 1. A compatible fork

The 1.5.2 public API (`AMIClient(**config)`, `register_event`, `create_action`, `create_asyncio_task`, `connect`, `connect_ami`, `connection_close`) and the private `_send_action(action, callback)` keep working, because existing users depend on them. New behaviour is additive or opt-in; a fix changes existing behaviour only where 1.5.2 crashed, hung or leaked.
