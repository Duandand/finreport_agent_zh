from agent import run_agent

if __name__ == "__main__":
    while True:
        q = input("Q: ")
        if q in ("exit", "quit"): break
        ans = run_agent(q)
        print("A:", ans["answer"])
        print("引用:", ans.get("citations", []))