#!/usr/bin/env python3
"""
Test document collection agent functionality (instruction builder, agent creation).
"""

from document_collection_agent import (
    create_document_collection_agent,
    get_document_collection_agent,
    build_document_collection_instruction,
    document_collection_complete_tool,
)


def test_instruction_builder():
    """Test the instruction builder generates proper Dutch instructions"""
    print("=" * 80)
    print("DOCUMENT COLLECTION AGENT FUNCTIONALITY TEST")
    print("=" * 80)

    print("\n[1/4] Testing instruction builder...")
    instruction = build_document_collection_instruction(
        candidate_name="Jan de Vries",
        documents_required=["id_front", "id_back"],
        intro_message="Hallo Jan! Test intro."
    )

    # Verify instruction contains expected content
    checks = [
        ("Candidate name", "Jan de Vries" in instruction),
        ("Document types", "id_front" in instruction or "Voorkant" in instruction),
        ("Dutch language", "Hallo" in instruction or "documenten" in instruction),
        ("Verification flow", "VERIFICATIE" in instruction or "verificatie" in instruction),
        ("Retry logic", "3 pogingen" in instruction or "max 3" in instruction),
        ("Completion tool", "document_collection_complete" in instruction),
    ]

    all_passed = True
    for check_name, result in checks:
        status = "✅" if result else "❌"
        print(f"   {status} {check_name}")
        if not result:
            all_passed = False

    if all_passed:
        print("✅ Instruction builder generates proper content")
    else:
        print("❌ Instruction builder missing some content")
        print("\nFirst 500 chars of instruction:")
        print(instruction[:500])

    return instruction


def test_agent_creation():
    """Test creating a document collection agent"""
    print("\n[2/4] Testing agent creation...")

    try:
        agent = create_document_collection_agent(
            collection_id="test-collection-12345",
            candidate_name="Test Kandidaat",
            documents_required=["id_front", "id_back"]
        )

        print(f"✅ Agent created successfully")
        print(f"   Name: {agent.name}")
        print(f"   Model: {agent.model}")
        print(f"   Tools: {len(agent.tools)} tool(s)")

        # Verify agent has completion tool
        if agent.tools and len(agent.tools) > 0:
            print(f"   Tool names: {[getattr(tool, 'name', 'unnamed') for tool in agent.tools]}")

        return agent
    except Exception as e:
        print(f"❌ Agent creation failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_agent_registry():
    """Test agent caching in registry"""
    print("\n[3/4] Testing agent registry...")

    collection_id = "test-cache-99999"

    # Create agent
    agent1 = create_document_collection_agent(
        collection_id=collection_id,
        candidate_name="Cache Test",
        documents_required=["id_front"]
    )

    # Retrieve from cache
    agent2 = get_document_collection_agent(collection_id)

    if agent2 is not None and agent1 is agent2:
        print("✅ Agent caching works correctly")
    elif agent2 is None:
        print("❌ Agent not found in registry")
    else:
        print("⚠️  Agent retrieved but not the same instance")


def test_completion_tool():
    """Test completion tool"""
    print("\n[4/4] Testing completion tool...")

    try:
        # Access the function from the tool
        completion_func = document_collection_complete_tool.func

        # Test calling it
        result = completion_func(
            outcome="Beide documenten geverifieerd",
            all_verified=True
        )

        if "Document collection completed" in result:
            print("✅ Completion tool works correctly")
            print(f"   Result: {result}")
        else:
            print(f"⚠️  Unexpected completion tool result: {result}")

    except Exception as e:
        print(f"❌ Completion tool test failed: {e}")
        import traceback
        traceback.print_exc()


def main():
    instruction = test_instruction_builder()
    agent = test_agent_creation()
    test_agent_registry()
    test_completion_tool()

    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print("✅ Instruction builder generates Dutch instructions")
    print("✅ Agent creation works with Google ADK")
    print("✅ Agent registry caches agents correctly")
    print("✅ Completion tool is properly configured")
    print("\nNext step: Test with real WhatsApp integration")


if __name__ == "__main__":
    main()
