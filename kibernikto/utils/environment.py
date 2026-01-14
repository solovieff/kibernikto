import logging

import logfire


def configure_logger():
    logfire.configure(service_name='holi:rebalancer')
    logfire.instrument_pydantic_ai()

    # XXX: this will push all logging to logfire
    logging.basicConfig(handlers=[logfire.LogfireLoggingHandler()])
