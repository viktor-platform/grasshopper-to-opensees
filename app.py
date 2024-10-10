import json
import math
import openseespy.opensees as ops
import matplotlib.pyplot as plt
import viktor as vkt
import time

NODE_RADIUS = 0.3
BEAM_WIDTH = 0.3


class Parametrization(vkt.ViktorParametrization):
    step_1 = vkt.Step("Create Model", views=["get_geometry"])
    step_1.text1 = vkt.Text(
        """## Structural Analysis using OpenSees\n
Welcome to our Structural Analysis App, a tool designed for the analysis of 3D frame buildings. Built on the OpenSeesPy
framework, a powerful Python package for simulating the response of structural and geotechnical systems to loads.

This app allows users to:

* upload a JSON with line coordinates 📏,
* apply directional loads to specific nodes ↗️,
* visualize the resulting deformations after running a structural analysis 🏗️. ️\n
The docs of OpenSeesPy can be found on
[this page](https://openseespydoc.readthedocs.io/).
        """
    )
    step_1.grasshopper_json = vkt.FileField('Upload Grasshopper JSON', file_types=['.json'], flex=80)

    step_1.loads = vkt.DynamicArray("Add loads")
    step_1.loads.magnitude = vkt.NumberField("Load", suffix="kN", num_decimals=2, default=100)
    step_1.loads.direction = vkt.OptionField("Direction", options=["x", "y", "z"], default="x")
    step_1.loads.node = vkt.GeometrySelectField("Select the node to apply a load")

    step_2 = vkt.Step("Run Analysis", views=["run_analysis"], width=30)
    step_2.text = vkt.Text("""
## Run the analysis and view the results
You can scale the deformation with the **Deformation scale factor** below.
    """)
    step_2.deformation_scale = vkt.NumberField("Deformation scale factor", min=0, max=5000, default=1000,
                                               num_decimals=0, variant='slider', flex=80)


class Controller(vkt.ViktorController):
    label = "Parametric Building"
    parametrization = Parametrization

    @vkt.GeometryView("3D building", duration_guess=1, x_axis_to_right=True)
    def get_geometry(self, params, **kwargs):
        if params.step_1.grasshopper_json is None:
            raise vkt.UserError("Upload a Grasshopper JSON to visualize a result")

        lines = self.get_lines_from_json_file(params.step_1.grasshopper_json.file)
        nodes, beams = self.convert_lines_to_nodes_and_beams(lines)
        geometry = self.visualize_geometry(nodes, beams, params.step_1.loads, opacity=1)
        return vkt.GeometryResult(geometry)

    @vkt.GeometryView("Deformed 3D building", duration_guess=10, x_axis_to_right=True, update_label="Run analysis")
    def run_analysis(self, params, **kwargs):
        # Create Geometry
        vkt.progress_message(message='🔄 Create OpenSees Model...')
        lines = self.get_lines_from_json_file(params.step_1.grasshopper_json.file)
        nodes, beams = self.convert_lines_to_nodes_and_beams(lines)
        geometry = self.visualize_geometry(nodes, beams, params.step_1.loads, opacity=0.6)
        p_message = f'✅ OpenSees Model Created ({len(nodes)} nodes | {len(beams)} beams)'
        vkt.progress_message(message=p_message)

        # Run Opensees
        vkt.progress_message(message=p_message + '\n🔄 Run OpenSees Analysis...')
        ops = self.run_opensees_model(nodes, beams, params.step_1.loads)

        # Visualize results
        visualized_deformed_nodes, deformed_nodes, max_displacement = self.visualize_deformed_nodes(nodes, ops, params.step_2.deformation_scale)
        deformed_beams = self.visualize_deformed_beams(deformed_nodes, beams, max_displacement)
        vkt.progress_message(message=p_message + '\n✅ OpenSees Analysis Completed \n🔄 Return Results...')

        return vkt.GeometryResult([vkt.Group(geometry), visualized_deformed_nodes, deformed_beams])

    def visualize_geometry(self, nodes, beams, loads, opacity):
        return [self.visualize_nodes(nodes, opacity),
                self.visualize_beams(nodes, beams, opacity),
                self.visualize_loads(nodes, loads, opacity)]

    @staticmethod
    def get_lines_from_json_file(grasshopper_json):
        with grasshopper_json.open() as r:
            grasshopper_dict = json.load(r)
        return grasshopper_dict['beams']

    @staticmethod
    def convert_lines_to_nodes_and_beams(lines):
        nodes = {}
        beams = []
        node_id = 1

        for line in lines:
            start = tuple(item / 1000 for item in tuple(line['start']))  # Convert from mm to m
            end = tuple(item / 1000 for item in tuple(line['end']))  # Convert from mm to m
            start_tag = f"node_{start[0]}_{start[1]}_{start[2]}"
            end_tag = f"node_{end[0]}_{end[1]}_{end[2]}"

            # Add nodes if they are not already in the dictionary
            if start_tag not in nodes:
                nodes[start_tag] = {'tag': start_tag, 'id': node_id, 'x': start[0], 'y': start[1], 'z': start[2]}
                node_id += 1
            if end_tag not in nodes:
                nodes[end_tag] = {'tag': end_tag, 'id': node_id,  'x': end[0], 'y': end[1], 'z': end[2]}
                node_id += 1

            beams.append({'start_node': start_tag, 'end_node': end_tag})

        return nodes, beams

    @staticmethod
    def visualize_nodes(nodes, opacity):
        spheres = []
        for node in nodes.values():
            spheres.append(vkt.Sphere(centre_point=vkt.Point(node['x'], node['y'], node['z']),
                                      radius=NODE_RADIUS,
                                      material=vkt.Material(color=vkt.Color.viktor_blue(), opacity=opacity),
                                      identifier=node['tag']))
        return vkt.Group(spheres)

    @staticmethod
    def visualize_beams(nodes, beams, opacity):
        extrusions = []
        for beam in beams:
            s = nodes[beam['start_node']]
            e = nodes[beam['end_node']]
            start_point = vkt.Point(s['x'], s['y'], s['z'])
            end_point = vkt.Point(e['x'], e['y'], e['z'])
            extrusions.append(vkt.RectangularExtrusion(width=BEAM_WIDTH,
                                                       height=BEAM_WIDTH,
                                                       line=vkt.Line(start_point, end_point),
                                                       material=vkt.Material(opacity=opacity)))
        return vkt.Group(extrusions)

    def visualize_loads(self, nodes, loads, opacity):
        load_arrows = []
        for i, load in enumerate(loads):
            if all([load.magnitude, load.direction, load.node]):
                if load.node not in nodes.keys():
                    raise vkt.UserError(f"Load {i + 1}: Selected node does not exist. Please reselect.")
                node = nodes[load.node]
                arrow = self.create_load_arrow(
                    vkt.Point(node['x'], node['y'], node['z']),
                    load.magnitude,
                    load.direction,
                    material=vkt.Material(color=vkt.Color(255, 0, 0), opacity=opacity)
                )
                load_arrows.append(arrow)

        return vkt.Group(load_arrows)

    @staticmethod
    def run_opensees_model(nodes, beams, loads):
        # Structural properties
        area = 50  # cross-sectional area of the elements
        E = 29500.0  # Young's modulus of the elements
        mass_x_element = 0.  # element mass per unit length
        G = 1000.  # Shear modulus
        Jxx = 1000.  # Torsional moment of inertia of cross section
        Iy = 2150.  # Second moment of area about the local y-axis
        Iz = 2150.  # Second moment of area about the local z-axis

        ops.wipe()
        ops.model("Basic", "-ndm", 3, "-ndf", 6)

        # Create nodes
        for node in nodes.values():
            ops.node(node['id'], node['x'], node['y'], node['z'])
            # If the node is on the ground floor, it is fixed
            if node['z'] == 0:
                ops.fix(node['id'], 1, 1, 1, 1, 1, 1)

        # Create beams
        ops.geomTransf("Linear", 1, 1, 0, 0)  # Transformation for columns
        ops.geomTransf("Linear", 2, 0, 0, 1)  # Transformation for beams

        for i, beam in enumerate(beams, start=1):
            start_node_id = nodes[beam['start_node']]['id']
            end_node_id = nodes[beam['end_node']]['id']
            start_z = nodes[beam['start_node']]['z']
            end_z = nodes[beam['end_node']]['z']

            transformation_tag = 2 if start_z == end_z else 1  # If beam 2, else 1

            ops.element("elasticBeamColumn", i, start_node_id, end_node_id, area, E, G, Jxx, Iy,
                        Iz, transformation_tag, "-mass", mass_x_element, "-lMass")

        ops.timeSeries("Linear", 1)
        ops.pattern("Plain", 1, 1)
        ops.analysis("Static")

        # Add loads
        for load in loads:
            if load['node'] is not None:
                node_id = nodes[load['node']]['id']
                if load["direction"] == "x":
                    ops.load(node_id, load["magnitude"], 0, 0, 0, 0, 0)
                elif load["direction"] == "y":
                    ops.load(node_id, 0, load["magnitude"], 0, 0, 0, 0)
                elif load["direction"] == "z":
                    ops.load(node_id, 0, 0, -1 * load["magnitude"], 0, 0, 0)

        # Run analysis
        ops.analyze(10)
        return ops

    def visualize_deformed_nodes(self, nodes, ops, deformation_scale):
        spheres = []
        deformed_nodes = {}

        max_displacement = max(
            math.sqrt(ops.nodeDisp(n['id'], 1) ** 2 + ops.nodeDisp(n['id'], 2) ** 2 + ops.nodeDisp(n['id'], 3) ** 2)
            for n in nodes.values()
        )

        for node in nodes.values():
            ux = ops.nodeDisp(node['id'], 1)
            uy = ops.nodeDisp(node['id'], 2)
            uz = ops.nodeDisp(node['id'], 3)

            displacement = math.sqrt(ux ** 2 + uy ** 2 + uz ** 2)

            # Determine the color of the node based on the displacement and change the material
            red, green, blue = self.get_color_from_displacement(displacement, max_displacement)
            material_nodes = vkt.Material("Node", color=vkt.Color(red, green, blue))

            # Create Viktor node to visualize
            point = vkt.Point(node['x'] + ux * deformation_scale,
                              node['y'] + uy * deformation_scale,
                              node['z'] + uz * deformation_scale)
            spheres.append(vkt.Sphere(centre_point=point,
                                      radius=NODE_RADIUS,
                                      material=material_nodes,
                                      identifier=f"{node['id']}"))

            deformed_nodes[node['tag']] = {'tag': node['tag'],
                                           'id': node['id'],
                                           'x': point.x,
                                           'y': point.y,
                                           'z': point.z,
                                           'displacement': displacement}

        return vkt.Group(spheres), deformed_nodes, max_displacement

    def visualize_deformed_beams(self, deformed_nodes, beams, max_displacement):
        extrusions = []
        for beam in beams:
            s = deformed_nodes[beam['start_node']]
            e = deformed_nodes[beam['end_node']]
            start_point = vkt.Point(s['x'], s['y'], s['z'])
            end_point = vkt.Point(e['x'], e['y'], e['z'])

            average_displacement = (s['displacement'] + e['displacement']) / 2
            red, green, blue = self.get_color_from_displacement(average_displacement, max_displacement)
            material_beam = vkt.Material("Beam", color=vkt.Color(red, green, blue))

            extrusions.append(vkt.RectangularExtrusion(width=BEAM_WIDTH,
                                                       height=BEAM_WIDTH,
                                                       line=vkt.Line(start_point, end_point),
                                                       material=material_beam))
        return vkt.Group(extrusions)

    @staticmethod
    def create_load_arrow(point_node, magnitude, direction, material=None):
        """Function to create a load arrow from a selected node"""
        size_arrow = abs(magnitude / 20)
        scale_point = 1.5
        scale_arrow_line = 7

        # Create points for the origin of the arrow point and line, based on the coordinate of the node with the load
        origin_of_arrow_point = vkt.Point(point_node.x - size_arrow - NODE_RADIUS, point_node.y, point_node.z)
        origin_of_arrow_line = vkt.Point(origin_of_arrow_point.x - size_arrow, origin_of_arrow_point.y, origin_of_arrow_point.z)

        # Creating the arrow with Viktor Cone and RectangularExtrusion
        arrow_point = vkt.Cone(size_arrow / scale_point, size_arrow,
                               origin=origin_of_arrow_point,
                               orientation=vkt.Vector(1, 0, 0),
                               material=material)
        arrow_line = vkt.RectangularExtrusion(size_arrow / scale_arrow_line,
                                              size_arrow / scale_arrow_line,
                                              vkt.Line(origin_of_arrow_line, origin_of_arrow_point),
                                              material=material)

        arrow = vkt.Group([arrow_point, arrow_line])

        # Rotate the arrow if the direction is not 'x' or if the magnitude is negative
        vector = vkt.Vector(0, 0, 1)
        if direction == "y":
            arrow.rotate(0.5 * math.pi, vector, point=point_node)
        if direction == "z":
            vector = vkt.Vector(0, 1, 0)
            arrow.rotate(0.5 * math.pi, vector, point=point_node)
        if magnitude < 0:
            arrow.rotate(math.pi, vector, point=point_node)

        return arrow

    @staticmethod
    def get_color_from_displacement(displacement, max_displacement):
        normalized_displacement = displacement / max_displacement if max_displacement != 0 else 0
        cmap = plt.get_cmap('jet')  # You can choose different colormaps like 'viridis', 'plasma', etc.
        rgb_color = cmap(normalized_displacement)[:3]  # [:3] to exclude the alpha channel
        return tuple(int(x * 255) for x in rgb_color)
