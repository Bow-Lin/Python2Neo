import ast
from neomodel import config, StructuredNode, StringProperty, RelationshipTo, db

# 设置Neo4j连接
config.DATABASE_URL = 'bolt://neo4j:password@localhost:7687'

# 定义数据模型
class ClassNode(StructuredNode):
    name = StringProperty(unique_index=True)
    methods = RelationshipTo('MethodNode', 'HAS_METHOD')
    attributes = RelationshipTo('AttributeNode', 'HAS_ATTRIBUTE')

class MethodNode(StructuredNode):
    name = StringProperty(index=True)
    args = StringProperty()

class AttributeNode(StructuredNode):
    name = StringProperty(index=True)

# 1. 解析Python文件结构
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
            # 提取函数
            for item in node.body:
                if isinstance(item, ast.FunctionDef) or isinstance(item, ast.AsyncFunctionDef):
                    args = [arg.arg for arg in item.args.args if arg.arg != 'self']
                    class_info["methods"].append({
                        "name": item.name,
                        "args": args
                    })
                # 提取类属性
                elif isinstance(item, ast.Assign) and len(item.targets) == 1:
                    if isinstance(item.targets[0], ast.Name):
                        class_info["attributes"].append(item.targets[0].id)
            classes.append(class_info)
    return classes

# 2. 清除数据库中的旧数据（用于测试）
def clear_database():
    db.cypher_query("MATCH (n) DETACH DELETE n")

# 3. 将数据存储到Neo4j
def save_to_neo4j(classes):
    for cls in classes:
        # 创建类节点
        class_node = ClassNode(name=cls["name"]).save()
        
        # 创建方法节点和关系
        for method in cls["methods"]:
            method_node = MethodNode(
                name=method["name"],
                args=", ".join(method["args"])
            ).save()
            class_node.methods.connect(method_node)
        
        # 创建属性节点和关系
        for attr in cls["attributes"]:
            attr_node = AttributeNode(name=attr).save()
            class_node.attributes.connect(attr_node)

if __name__ == "__main__":
    # 清除数据库（可选）
    clear_database()
    
    # 解析Python文件并保存到Neo4j
    parsed_classes = parse_python_file("./code-evaluator.py")  # 目标文件路径
    save_to_neo4j(parsed_classes)
    print("数据已成功加载到Neo4j")