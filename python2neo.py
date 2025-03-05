import ast
from py2neo import Graph, Node, Relationship

# 1. Parse Python file structure
def parse_python_file(file_path):
    with open(file_path, "r") as f:
        tree = ast.parse(f.read())
    
    classes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            class_info = {
                "name": node.name,
                "methods": [],
                "attributes": []
            }
            # Extract Functions
            for item in node.body:
                if isinstance(item, ast.FunctionDef) or isinstance(item, ast.AsyncFunctionDef):
                    args = [arg.arg for arg in item.args.args if arg.arg != 'self']
                    class_info["methods"].append({
                        "name": item.name,
                        "args": args
                    })
                # Extract Class attribute
                elif isinstance(item, ast.Assign) and isinstance(item.targets, ast.Name):
                    class_info["attributes"].append(item.targets.id)
            classes.append(class_info)
    return classes

# 2. Connect to Neo4j database
graph = Graph("bolt://localhost:7687", auth=("neo4j", "password"))
graph.delete_all()  # clear old data(for testing)

# 3. Store data to Neo4j
def save_to_neo4j(classes):
    for cls in classes:
        # Create Class Node
        class_node = Node("Class", name=cls["name"])
        graph.create(class_node)
        
        # Create Method node and Relationship
        for method in cls["methods"]:
            method_node = Node("Method", 
                name=method["name"], 
                args=", ".join(method["args"])
            )
            rel = Relationship(class_node, "HAS_METHOD", method_node)
            graph.create(method_node)
            graph.create(rel)
        
        # Create Attribute node and Relationship
        for attr in cls["attributes"]:
            attr_node = Node("Attribute", name=attr)
            rel = Relationship(class_node, "HAS_ATTRIBUTE", attr_node)
            graph.create(attr_node)
            graph.create(rel)

if __name__ == "__main__":
    parsed_classes = parse_python_file("./code-evaluator.py")  # target file path
    save_to_neo4j(parsed_classes)
    print("data successfully load to Neo4j")
