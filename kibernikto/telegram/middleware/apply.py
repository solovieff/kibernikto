from aiogram import Dispatcher


def apply_default_middlewares(dispatcher: Dispatcher):
    from kibernikto.telegram.middleware.middleware_firewall import FirewallMiddleware
    from kibernikto.telegram.middleware.middleware_subscription import SubscriptionMiddleware

    from kibernikto.telegram.middleware.middleware_service import ServiceMiddleware

    middlewares = [ServiceMiddleware, FirewallMiddleware, SubscriptionMiddleware]

    for middleware in middlewares:
        middleware.apply_if_needed(dispatcher)
