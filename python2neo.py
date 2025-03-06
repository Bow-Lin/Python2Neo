import ast
from neomodel import config, StructuredNode, StringProperty, RelationshipTo, db

# Setup Neo4j connection
config.DATABASE_URL = 'bolt://neo4j:password@localhost:7687'

# Define data models
class ClassNode(StructuredNode):
    name = StringProperty(unique_index=True)
    methods = RelationshipTo('MethodNode', 'HAS_METHOD')
    attributes = RelationshipTo('AttributeNode', 'HAS_ATTRIBUTE')

class MethodNode(StructuredNode):
    name = StringProperty(index=True)
    args = StringProperty()

class AttributeNode(StructuredNode):
    name = StringProperty(index=True)

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
            # Extract methods
            for item in node.body:
                if isinstance(item, ast.FunctionDef) or isinstance(item, ast.AsyncFunctionDef):
                    args = [arg.arg for arg in item.args.args if arg.arg != 'self']
                    class_info["methods"].append({
                        "name": item.name,
                        "args": args
                    })
                # Extract class attributes
                elif isinstance(item, ast.Assign) and len(item.targets) == 1:
                    if isinstance(item.targets[0], ast.Name):
                        class_info["attributes"].append(item.targets[0].id)
            classes.append(class_info)
    return classes

# 2. Clear existing data in database (for testing)
def clear_database():
    db.cypher_query("MATCH (n) DETACH DELETE n")

# 3. Save data to Neo4j
def save_to_neo4j(classes):
    for cls in classes:
        # Create class node
        class_node = ClassNode(name=cls["name"]).save()
        
        # Create method nodes and relationships ‌
        for method in cls["methods"]:
            method_node = MethodNode(
                name=method["name"],
                args=", ".join(method["args"])
            ).save()
            class_node.methods.connect(method_node)
        
        # Create attribute nodes and relationships
        for attr in cls["attributes"]:
            attr_node = AttributeNode(name=attr).save()
            class_node.attributes.connect(attr_node)

if __name__ == "__main__":
    # Clear database (optional)
    clear_database()
    
    # Parse Python file and save to Neo4j
    parsed_classes = parse_python_file("./test.py")  # Target file path
    save_to_neo4j(parsed_classes)
    print("Data successfully loaded to Neo4j")