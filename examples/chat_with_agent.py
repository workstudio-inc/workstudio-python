"""
Example: Chat with AI Agents.

This example shows how to:
1. List available agents
2. Send single messages
3. Have multi-turn conversations
"""

from workstudio import Client

# Initialize client
client = Client()  # Uses WORKSTUDIO_API_KEY env var

# Example 1: List published agents
print("=== Available Agents ===")
agents, _ = client.agents.list(active=True)
for agent in agents:
    print(f"  - {agent.name}: {agent.description}")

# Example 2: Simple one-shot chat
print("\n=== One-Shot Chat ===")
response = client.agents.chat(
    "sales-assistant",  # agent name or ID
    "What are our top 3 deals this quarter?"
)
print(f"Response: {response.message}")
print(f"Tokens: {response.total_tokens} (${response.estimated_cost_usd:.4f})")

if response.tools_used:
    print(f"Tools used: {', '.join(response.tools_used)}")

# Example 3: Multi-turn conversation with context
print("\n=== Multi-Turn Conversation ===")
with client.agents.create_session("sales-assistant") as session:
    # First message
    r1 = session.send_message("What are our top deals?")
    print(f"User: What are our top deals?")
    print(f"Agent: {r1.message}\n")
    
    # Follow-up (agent remembers previous context)
    r2 = session.send_message("Tell me more about the first one")
    print(f"User: Tell me more about the first one")
    print(f"Agent: {r2.message}\n")
    
    # Another follow-up
    r3 = session.send_message("Who is the decision maker?")
    print(f"User: Who is the decision maker?")
    print(f"Agent: {r3.message}\n")
    
    # Check cumulative metrics
    state = session.get_state()
    print(f"Session metrics:")
    print(f"  - Total turns: {state.total_turns}")
    print(f"  - Total tokens: {state.total_tokens}")
    print(f"  - Total cost: ${state.total_cost_usd:.4f}")

# Session is automatically closed when exiting the 'with' block

client.close()
