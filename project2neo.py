import os
import ast
import importlib.util
from pathlib import Path
from neomodel import config, StructuredNode, StringProperty, RelationshipTo, db

# Neo4j 数据库配置
config.DATABASE_URL = 'bolt://neo4j:password@localhost:7687'

# 数据模型定义
class ModuleNode(StructuredNode):
    path = StringProperty(unique_index=True)  # 模块文件路径
    name = StringProperty(index=True)         # 模块名称
    classes = RelationshipTo('ClassNode', 'CONTAINS_CLASS')
    imports = RelationshipTo('ModuleNode', 'IMPORTS')

class ClassNode(StructuredNode):
    name = StringProperty(index=True)
    full_name = StringProperty(unique_index=True)  # 模块.类名
    methods = RelationshipTo('MethodNode', 'HAS_METHOD')
    attributes = RelationshipTo('AttributeNode', 'HAS_ATTRIBUTE')

class MethodNode(StructuredNode):
    name = StringProperty(index=True)
    full_name = StringProperty(unique_index=True)  # 模块.类名.方法名
    args = StringProperty()

class AttributeNode(StructuredNode):
    name = StringProperty(index=True)
    full_name = StringProperty(unique_index=True)  # 模块.类名.属性名

# 获取导入信息的访问者类
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

# 清除数据库中的所有数据
def clear_database():
    db.cypher_query("MATCH (n) DETACH DELETE n")

# 解析Python文件结构并收集导入信息
def parse_python_file(file_path, project_root):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            file_content = f.read()
        
        tree = ast.parse(file_content)
        
        # 获取导入信息
        import_visitor = ImportVisitor()
        import_visitor.visit(tree)
        imports = import_visitor.imports
        
        # 获取模块相对路径
        rel_path = os.path.relpath(file_path, project_root)
        module_path = rel_path.replace(os.path.sep, '.')
        if module_path.endswith('.py'):
            module_path = module_path[:-3]
        
        # 收集类、方法和属性信息
        classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_info = {
                    "name": node.name,
                    "full_name": f"{module_path}.{node.name}",
                    "methods": [],
                    "attributes": []
                }
                
                # 提取函数
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) or isinstance(item, ast.AsyncFunctionDef):
                        args = [arg.arg for arg in item.args.args if arg.arg != 'self']
                        class_info["methods"].append({
                            "name": item.name,
                            "full_name": f"{module_path}.{node.name}.{item.name}",
                            "args": args
                        })
                    # 提取类属性
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

# 查找项目中所有Python文件并解析
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

# 将解析的项目结构保存到Neo4j
def save_project_to_neo4j(modules):
    # 创建一个映射，用于存储模块路径到ModuleNode的映射
    module_nodes = {}
    
    # 第一步：创建所有模块节点
    for module in modules:
        module_node = ModuleNode(
            path=module["path"],
            name=module["name"]
        ).save()
        module_nodes[module["path"]] = module_node
        
        # 创建该模块中的所有类、方法和属性节点
        for cls in module["classes"]:
            class_node = ClassNode(
                name=cls["name"],
                full_name=cls["full_name"]
            ).save()
            module_node.classes.connect(class_node)
            
            # 创建方法节点和关系
            for method in cls["methods"]:
                method_node = MethodNode(
                    name=method["name"],
                    full_name=method["full_name"],
                    args=", ".join(method["args"])
                ).save()
                class_node.methods.connect(method_node)
            
            # 创建属性节点和关系
            for attr in cls["attributes"]:
                attr_node = AttributeNode(
                    name=attr["name"],
                    full_name=attr["full_name"]
                ).save()
                class_node.attributes.connect(attr_node)
    
    # 第二步：创建模块之间的导入关系
    for module in modules:
        source_node = module_nodes.get(module["path"])
        if not source_node:
            continue
            
        for import_name in module["imports"]:
            # 尝试匹配导入的模块
            for target_module in modules:
                if target_module["name"] == import_name or target_module["name"].endswith("." + import_name):
                    target_node = module_nodes.get(target_module["path"])
                    if target_node and target_node != source_node:
                        # 创建导入关系
                        source_node.imports.connect(target_node)
                        break

# 主函数 - 从项目顶层运行
def process_project(project_root="."):
    print(f"开始处理项目: {os.path.abspath(project_root)}")
    
    # 清除数据库（可选）
    print("清除数据库中的旧数据...")
    clear_database()
    
    # 解析项目中的所有Python文件
    print("解析Python文件...")
    modules = find_and_parse_python_files(project_root)
    print(f"找到 {len(modules)} 个Python模块")
    
    # 保存到Neo4j
    print("保存项目结构到Neo4j...")
    save_project_to_neo4j(modules)
    
    print("项目结构已成功加载到Neo4j数据库")

if __name__ == "__main__":
    import sys
    # 默认使用当前目录作为项目根目录，或者使用命令行传入的路径
    project_root = sys.argv[1] if len(sys.argv) > 1 else "."
    process_project(project_root)