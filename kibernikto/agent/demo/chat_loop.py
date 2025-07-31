from kibernikto.agent.kibernikto_agent import KiberniktoAgent
from kibernikto.utils.telegram import timer


async def main_loop(agent: KiberniktoAgent):
    while True:
        # Prompt the user for input
        question = input(">>> ")

        # Check if the user wants to exit
        if question.lower() == 'exit':
            print("Exiting...")
            break

        # Use the question in your request
        with timer(f"📲 {agent.label} call"):
            # one for all the calls. unique value here to have it one for a real user call.
            reply = await agent.query(question, effort_level=10, save_to_history=True, call_session_id=f"{agent.label}-only-session")
            print(f"\n📺 {reply}\n")
