import adsk.core, adsk.fusion, traceback, os, struct, re, subprocess, sys

# Base output folder — Windows Documents
BASE_FOLDER = os.path.join(os.path.expanduser("~"), "Documents", "car_stls")

# Path to aws_study.py — adjust if you move it
AWS_STUDY_PATH = os.path.join(os.path.expanduser("~"), "Documents", "f1-cfd", "aws_study.py")

def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface
        design = app.activeProduct
        root   = design.rootComponent

        # Ask user for folder name
        result, cancelled = ui.inputBox(
            'Enter a name for this export (e.g. "run_01", "v2_low_drag"):',
            'Export Folder Name',
            ''
        )
        if cancelled or not result.strip():
            ui.messageBox('Export cancelled — no folder name provided.')
            return

        # Sanitise: replace spaces with underscores, strip illegal chars
        folder_name = re.sub(r'[\\/:*?"<>|]', '', result.strip()).replace(' ', '_')
        if not folder_name:
            ui.messageBox('Invalid folder name. Export cancelled.')
            return

        export_folder = os.path.join(BASE_FOLDER, folder_name)

        # Prevent accidental overwrite
        if os.path.exists(export_folder):
            confirm, cancelled = ui.inputBox(
                f'Folder "{folder_name}" already exists. Overwrite? (yes/no):',
                'Confirm Overwrite',
                'no'
            )
            if cancelled or confirm.strip().lower() != 'yes':
                ui.messageBox('Export cancelled.')
                return

        os.makedirs(export_folder, exist_ok=True)

        mgr = design.exportManager

        car_bodies   = []
        front_wheels = []
        rear_wheels  = []

        def categorise(body):
            if not body.isVisible:
                return
            name = body.name.lower()
            if 'wheel' not in name:
                car_bodies.append(body)
            elif 'front' in name:
                front_wheels.append(body)
            elif 'rear' in name or 'back' in name:
                rear_wheels.append(body)
            else:
                ui.messageBox(f'Body "{body.name}" has "wheel" in name but no front/rear — skipping.')

        for body in root.bRepBodies:
            categorise(body)
        for occ in root.allOccurrences:
            for body in occ.bRepBodies:
                categorise(body)

        def combine_bodies(bodies):
            if len(bodies) == 1:
                return bodies[0]
            combines = root.features.combineFeatures
            target = bodies[0]
            tool_bodies = adsk.core.ObjectCollection.create()
            for b in bodies[1:]:
                tool_bodies.add(b)
            combine_input = combines.createInput(target, tool_bodies)
            combine_input.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
            combine_input.isKeepToolBodies = False
            combine_input.isNewComponent = False
            combine_feature = combines.add(combine_input)
            return combine_feature.bodies.item(0)

        # Fusion internal units are mm → metres: multiply by 0.01
        MM_TO_M = 0.01

        def get_world_transform(body):
            """Return the world transform for a body, walking the occurrence tree."""
            for occ in root.allOccurrences:
                for b in occ.bRepBodies:
                    if b.entityToken == body.entityToken:
                        return occ.worldTransform
            return adsk.core.Matrix3D.create()  # root-level body → identity

        def export_body(body, filename, patch_name):
            """
            Tessellate body, apply world transform, convert mm→m,
            write single-patch binary STL with patch_name in header.
            """
            calc = body.meshManager.createMeshCalculator()
            calc.setQuality(adsk.fusion.TriangleMeshQualityOptions.HighQualityTriangleMesh)
            mesh = calc.calculate()

            xform   = get_world_transform(body)
            coords  = mesh.nodeCoordinates
            indices = mesh.nodeIndices

            path = os.path.join(export_folder, filename)
            with open(path, 'wb') as f:
                header = patch_name.encode('ascii')[:80].ljust(80, b' ')
                f.write(header)
                tri_count = len(indices) // 3
                f.write(struct.pack('<I', tri_count))

                for i in range(tri_count):
                    i0, i1, i2 = indices[i*3], indices[i*3+1], indices[i*3+2]

                    pts = []
                    for idx in (i0, i1, i2):
                        p = coords[idx].copy()
                        p.transformBy(xform)
                        pts.append((p.x * MM_TO_M, p.y * MM_TO_M, p.z * MM_TO_M))

                    ax = pts[1][0]-pts[0][0]; ay = pts[1][1]-pts[0][1]; az = pts[1][2]-pts[0][2]
                    bx = pts[2][0]-pts[0][0]; by = pts[2][1]-pts[0][1]; bz = pts[2][2]-pts[0][2]
                    nx = ay*bz - az*by; ny = az*bx - ax*bz; nz = ax*by - ay*bx
                    L  = (nx*nx + ny*ny + nz*nz) ** 0.5
                    if L > 0:
                        nx /= L; ny /= L; nz /= L

                    f.write(struct.pack('<12fH',
                        nx, ny, nz,
                        pts[0][0], pts[0][1], pts[0][2],
                        pts[1][0], pts[1][1], pts[1][2],
                        pts[2][0], pts[2][1], pts[2][2],
                        0  # zero attr = single patch
                    ))

        exported = []

        if not car_bodies:
            ui.messageBox('Warning: No car body bodies found — skipping car_body.stl')
        else:
            combined = combine_bodies(car_bodies)
            export_body(combined, 'car_body.stl', 'car_body')
            exported.append('car_body.stl')

        if not front_wheels:
            ui.messageBox('Warning: No front wheel bodies found — skipping wheel_front.stl')
        else:
            combined = combine_bodies(front_wheels)
            export_body(combined, 'wheel_front.stl', 'wheel_front')
            exported.append('wheel_front.stl')

        if not rear_wheels:
            ui.messageBox('Warning: No rear wheel bodies found — skipping wheel_rear.stl')
        else:
            combined = combine_bodies(rear_wheels)
            export_body(combined, 'wheel_rear.stl', 'wheel_rear')
            exported.append('wheel_rear.stl')

        if not exported:
            ui.messageBox('No files were exported. Check your body names.')
            return

        # Ask debug mode
        debug_ans, cancelled = ui.inputBox(
            'Run in DEBUG mode? (fast/low-quality mesh, 2+3 iterations)\nType "yes" for debug:',
            'Debug Mode',
            'no'
        )
        debug_mode = (not cancelled) and debug_ans.strip().lower() == 'yes'
        debug_flag = ' --debug' if debug_mode else ''


        ui.messageBox(
            f'Export complete!\n\nSaved to:\n{export_folder}\n\nFiles:\n' +
            '\n'.join(exported) +
            '\n\nWorld coordinates preserved.\nScaled to metres.\nPatches named correctly.'
            + ('\n\n⚠ DEBUG MODE — low quality mesh, 2+3 iterations' if debug_mode else '\n\n→ Launching CFD simulation now...')
        )

        # ── Auto-launch aws_study.py ──────────────────────────────────────────
        # Check aws_study.py exists before trying to launch
        if not os.path.exists(AWS_STUDY_PATH):
            ui.messageBox(
                f'⚠ Could not find aws_study.py at:\n{AWS_STUDY_PATH}\n\n'
                'STLs were exported successfully.\n'
                'Run manually: python aws_study.py "' + export_folder + '"'
            )
            return

        # Launch in a new visible terminal window so the user can watch progress
        # Uses 'start' (Windows) to open a new cmd window
        cmd = f'start cmd /k "python \"{AWS_STUDY_PATH}\" \"{export_folder}\"{debug_flag}"'
        os.system(cmd)

        ui.messageBox(
            f'✅ CFD job submitted!\n\n'
            f'A terminal window has opened — watch it for progress.\n'
            f'Job name: {folder_name}\n\n'
            + ('\n⚠ DEBUG MODE — results not meaningful.\n' if debug_mode else '')
            + 'Results will appear in Firebase when done.'
        )

    except:
        if ui:
            ui.messageBox('Error:\n{}'.format(traceback.format_exc()))
