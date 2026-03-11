
import json
from pathlib import Path

# Path to the compiled ink.json
file_path = "/Users/peterbailey/zforge/experiences/pyrrhia/the-scavenger-and-the-mudwing-s-muddle.ink.json"

def inspect_ink():
    print(f"--- Inspecting: {file_path} ---")
    try:
        content = Path(file_path).read_text()
        data = json.loads(content)
        
        print(f"Keys found in JSON: {list(data.keys())}")
        
        excluded = ["inkVersion", "root", "listDefs"]
        story_keys = [k for k in data.keys() if k not in excluded]
        print(f"Potential Story Knots (non-metadata): {story_keys}")
        
        if "root" in data:
            # Look at first few elements of root for diverts
            root = data["root"]
            print(f"Root elements count: {len(root)}")
            print(f"First few elements of root: {json.dumps(root[:5], indent=2)}")
            
        if not story_keys:
            print("CRITICAL: No story knots found outside of metadata!")
            
    except Exception as e:
        print(f"Error during inspection: {e}")

if __name__ == "__main__":
    inspect_ink()
