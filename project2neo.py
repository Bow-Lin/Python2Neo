import os
import ast
import importlib.util
from pathlib import Path
from neomodel import config, StructuredNode, StringProperty, RelationshipTo, db

# Setup Neo4j connection
config.DATABASE_URL = 'bolt://neo4j:password@localhost:7687'

# Define data models
class ModuleNode(StructuredNode):
    path = StringProperty(unique_index=True)  # module path
    name = StringProperty(index=True)         # module name
    classes = RelationshipTo('ClassNode', 'CONTAINS_CLASS')
    imports = RelationshipTo('ModuleNode', 'IMPORTS')

class ClassNode(StructuredNode):
    name = StringProperty(index=True)
    full_name = StringProperty(unique_index=True)  # module.classname
    methods = RelationshipTo('MethodNode', 'HAS_METHOD')
    attributes = RelationshipTo('AttributeNode', 'HAS_ATTRIBUTE')

class MethodNode(StructuredNode):
    name = StringProperty(index=True)
    full_name = StringProperty(unique_index=True)  # module.class.method
    args = StringProperty()

class AttributeNode(StructuredNode):
    name = StringProperty(index=True)
    full_name = StringProperty(unique_index=True)  # module.class.attribute

# get importVisitor info
class ImportVisitor(ast.NodeVisitor):
    def __init__(self):
        self.imports = []

    def visit_Import(self, node):
        for name in node.names:
            self.imports.append(name.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            for name in node.names:
                if node.level == 0:  # 绝对导入
                    self.imports.append(f"{node.module}")
                else:  # 相对导入
                    self.imports.append(f".{'.' * (node.level-1)}{node.module}")
        self.generic_visit(node)

# Clear existing data in database (for testing)
def clear_database():
    db.cypher_query("MATCH (n) DETACH DELETE n")

# Parse Python file structures and collect import info
def parse_python_file(file_path, project_root):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            file_content = f.read()
        
        tree = ast.parse(file_content)
        
        # get import info
        import_visitor = ImportVisitor()
        import_visitor.visit(tree)
        imports = import_visitor.imports
        
        # Retrieve module relative paths
        rel_path = os.path.relpath(file_path, project_root)
        module_path = rel_path.replace(os.path.sep, '.')
        if module_path.endswith('.py'):
            module_path = module_path[:-3]
        
        # Collect class, method, and attribute information
        classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_info = {
                    "name": node.name,
                    "full_name": f"{module_path}.{node.name}",
                    "methods": [],
                    "attributes": []
                }
                
                # Extract methods
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) or isinstance(item, ast.AsyncFunctionDef):
                        args = [arg.arg for arg in item.args.args if arg.arg != 'self']
                        class_info["methods"].append({
                            "name": item.name,
                            "full_name": f"{module_path}.{node.name}.{item.name}",
                            "args": args
                        })
                    # Extract class attributes
                    elif isinstance(item, ast.Assign) and len(item.targets) == 1:
                        if isinstance(item.targets[0], ast.Name):
                            attr_name = item.targets[0].id
                            class_info["attributes"].append({
                                "name": attr_name,
                                "full_name": f"{module_path}.{node.name}.{attr_name}" 
                            })
                            
                classes.append(class_info)
        
        return {
            "path": file_path,
            "name": module_path,
            "imports": imports,
            "classes": classes
        }
    except Exception as e:
        print(f"Error parsing {file_path}: {e}")
        return {
            "path": file_path,
            "name": os.path.relpath(file_path, project_root).replace(os.path.sep, '.'),
            "imports": [],
            "classes": []
        }

# Locate and parse all Python files in the project
def find_and_parse_python_files(project_root):
    project_root = os.path.abspath(project_root)
    modules = []
    
    for root, _, files in os.walk(project_root):
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                module_info = parse_python_file(file_path, project_root)
                modules.append(module_info)
    
    return modules

# Save parsed project to Neo4j
def save_project_to_neo4j(modules):
    # Create a map to store mappings from module paths to ModuleNode objects
    module_nodes = {}
    
    # First step: create all module nodes
    for module in modules:
        module_node = ModuleNode(
            path=module["path"],
            name=module["name"]
        ).save()
        module_nodes[module["path"]] = module_node
        
        # Create all class, method, attribute nodes in the module
        for cls in module["classes"]:
            class_node = ClassNode(
                name=cls["name"],
                full_name=cls["full_name"]
            ).save()
            module_node.classes.connect(class_node)
            
            # Create method nodes and relationships 
            for method in cls["methods"]:
                method_node = MethodNode(
                    name=method["name"],
                    full_name=method["full_name"],
                    args=", ".join(method["args"])
                ).save()
                class_node.methods.connect(method_node)
            
            # Create attribute nodes and relationships
            for attr in cls["attributes"]:
                attr_node = AttributeNode(
                    name=attr["name"],
                    full_name=attr["full_name"]
                ).save()
                class_node.attributes.connect(attr_node)
    
    # Step 2: Establish import relationships between modules
    for module in modules:
        source_node = module_nodes.get(module["path"])
        if not source_node:
            continue
            
        for import_name in module["imports"]:
            # ‌Attempt to match imported modules
            for target_module in modules:
                if target_module["name"] == import_name or target_module["name"].endswith("." + import_name):
                    target_node = module_nodes.get(target_module["path"])
                    if target_node and target_node != source_node:
                        # Create import relationships
                        source_node.imports.connect(target_node)
                        break

# main function run at the top of project folder
def process_project(project_root="."):
    print(f"Start processing project: {os.path.abspath(project_root)}")
    
    # Clear database (optional)
    print("clear outdated data...")
    clear_database()
    
    # Parse all python file in the project and save to Neo4j
    print("Parsing Python files...")
    modules = find_and_parse_python_files(project_root)
    print(f"Find {len(modules)} python modules")
    
    # Save data to Neo4j
    print("Saving project strucure to Neo4j...")
    save_project_to_neo4j(modules)
    
    print("Project structure has been successfully loaded into the Neo4j database")

if __name__ == "__main__":
    import sys
    # Using current directory by default or use the path provided via cli args
    project_root = sys.argv[1] if len(sys.argv) > 1 else "."
    process_project(project_root)