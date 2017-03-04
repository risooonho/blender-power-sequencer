import os
import bpy
from bpy.props import BoolProperty, IntProperty

from .functions.global_settings import ProjectSettings, Extensions
from .functions.file_management import *
from .functions.animation import add_transform_effect
from .functions.sequences import find_empty_channel


# TODO: Fix img imported from subfolder -
# TODO: auto process img strips - add transform that scales it down to its original size
# and sets blend mode to alpha_over
# TODO: img crop and offset to make anim easier
# TODO: Import at cursor pos
class ImportLocalFootage(bpy.types.Operator):
    bl_idname = "gdquest_vse.import_local_footage"
    bl_label = "Import local footage"
    bl_description = "Import video and audio from the project folder to VSE strips"
    bl_options = {'REGISTER', 'UNDO'}

    import_all = BoolProperty(
        name="Always Reimport",
        description="If true, always import all local files to new strips. \
                    If False, only import new files (check if footage has \
                    already been imported to the VSE).",
        default=False)
    keep_audio = BoolProperty(
        name="Keep audio from video files",
        description=
        "If False, the audio that comes with video files will not be imported",
        default=True)

    img_length = IntProperty(
        name="Image strip length",
        description=
        "Controls the duration of the imported image strips length",
        default=96,
        min=1)
    img_padding = IntProperty(
        name="Image strip padding",
        description="Padding added between imported image strips in frames",
        default=24,
        min=1)

    # PSD related features
    # import_psd = BoolProperty(
    #     name="Import PSD as image",
    #     description="When True, psd files will be imported as individual image strips",
    #     default=False)
    # ps_assets_as_img = BoolProperty(
    #     name="Import PS assets as images",
    #     description="Imports the content of folders generated by Photoshop's quick export \
    #                 function as individual image strips",
    #     default=True)

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        if not bpy.data.is_saved:
            self.report(
                {"ERROR_INVALID_INPUT"},
                "You need to save your project first. Import cancelled.")
            return {"CANCELLED"}

        sequencer = bpy.ops.sequencer
        context = bpy.context
        frame_current = bpy.context.scene.frame_current
        empty_channel = find_empty_channel(mode='ABOVE')

        bpy.ops.screen.animation_cancel(restore_frame=True)

        for window in bpy.context.window_manager.windows:
            screen = window.screen
            for area in screen.areas:
                if area.type == 'SEQUENCE_EDITOR':
                    SEQUENCER_AREA = {'window': window,
                                      'screen': screen,
                                      'area': area,
                                      'scene': bpy.context.scene}

        from .load_files import get_working_directory
        directory = get_working_directory()
        folders, files, files_dict = {}, {}, {}

        file_types = "AUDIO", "IMG", "VIDEO"

        for folder in os.listdir(path=directory):
            folder_upper = folder.upper()
            if folder_upper in file_types:
                folders[folder_upper] = directory + "\\" + folder

        for name in file_types:
            walk_folders = True if name == "IMG" else False
            if name not in folders.keys():
                continue
            files[name] = find_files(folders[name],
                                     Extensions.DICT[name],
                                     recursive=walk_folders)

        TEXT_FILE_PREFIX = 'IMPORT_'
        texts = bpy.data.texts
        import_files = {}
        for name in file_types:
            if texts.get(TEXT_FILE_PREFIX + name):
                import_files[name] = texts[TEXT_FILE_PREFIX + name]

        if not import_files:
            from .functions.file_management import create_text_file
            for name in file_types:
                import_files[name] = create_text_file(TEXT_FILE_PREFIX + name)
            assert len(import_files) == 3

        # Write new imported paths to the text files and import new strips
        channel_offset = 0
        for name in file_types:
            if name not in folders.keys():
                continue

            text_file_content = [
                line.body
                for line in bpy.data.texts[TEXT_FILE_PREFIX + name].lines
            ]
            new_paths = [path
                         for path in files[name]
                         if path not in text_file_content]
            for line in new_paths:
                bpy.data.texts[TEXT_FILE_PREFIX + name].write(line + "\n")

            if not new_paths:
                continue

            import_channel = empty_channel + channel_offset
            folder = folders[name]
            files_dict = files_to_dict(new_paths, folder)

            created_sequences = []
            if name == "VIDEO":
                import_channel += 1 if self.keep_audio else 0
                sequencer.movie_strip_add(SEQUENCER_AREA,
                                          filepath=folder + "\\",
                                          files=files_dict,
                                          frame_start=frame_current,
                                          channel=import_channel,
                                          sound=self.keep_audio)
                created_sequences.extend(bpy.context.selected_sequences)
            elif name == "AUDIO":
                sequencer.sound_strip_add(SEQUENCER_AREA,
                                          filepath=folder + "\\",
                                          files=files_dict,
                                          frame_start=frame_current,
                                          channel=import_channel)
                created_sequences.extend(bpy.context.selected_sequences)
            elif name == "IMG":
                img_frame = frame_current
                for img in files_dict:
                    path = folder + "\\" + img['subfolder']
                    file = [{'name': img['name']}]

                    sequencer.image_strip_add(
                        SEQUENCER_AREA,
                        directory=path,
                        files=file,
                        frame_start=img_frame,
                        frame_end=img_frame + self.img_length,
                        channel=import_channel)
                    created_sequences.extend(bpy.context.selected_sequences)

                    img_frame += self.img_length + self.img_padding
                    img_strips = bpy.context.selected_sequences
                    # TODO: img crop and offset to make anim easier
                    # set_img_strip_offset(img_strips)
                    add_transform_effect(img_strips)
            channel_offset += 1

        for s in created_sequences:
            s.select = True
        return {"FINISHED"}


# TODO: Ignore the blender proxy folders
def find_files(directory,
               file_extensions,
               recursive=False,
               ignore_folders=('_proxy')):
    """
    Walks through a folder and returns a list of filepaths that match the extensions.
    Args:
        - file_extensions is a tuple of extensions with the form "*.ext". Use the Extensions helper class in .functions.global_settings. It gives default extensions to check the files against.
    """
    print(file_extensions)
    if not directory and file_extensions:
        return None

    files = []

    from glob import glob
    from os.path import basename

    # TODO: Folder containing img files = img sequence
    for ext in file_extensions:
        source_pattern = directory + "\\"
        pattern = source_pattern + ext
        files.extend(glob(pattern))
        if not recursive:
            continue
        pattern = source_pattern + "**\\" + ext
        files.extend(glob(pattern))

    if basename(directory) == "IMG":
        psd_names = [f for f in glob(directory + "\\*.psd")]
        for i, name in enumerate(psd_names):
            psd_names[i] = name[len(directory):-4]

        psd_folders = (f for f in os.listdir(directory) if f in psd_names)
        for f in psd_folders:
            for ext in file_extensions:
                files.extend(glob(directory + "\\" + f + "\\" + ext))
    return files


def files_to_dict(files, folder_path):
    """Converts a list of files to Blender's dictionary format for import
       Returns a list of dictionaries with the {'name': filename, 'subfolder': subfolder} format
       If the provided files are placed at the root of the import folders, subfolder will be an empty string
       Args:
        - files: a list or a tuple of files
        - folder_path: a string of the path to the files' containing folder"""
    if not files and folder_path:
        return None

    dictionary = []
    for f in files:
        filepath_tail = f[len(folder_path) + 1:]
        head, tail = os.path.split(filepath_tail)
        dict_form = {'name': tail, 'subfolder': head}
        dictionary.append(dict_form)
    return dictionary


# FIXME: Currently not getting image width and height (set to 0)
def add_transform_effect(sequences=None):
    """Takes a list of image strips and adds a transform effect to them.
       Ensures that the pivot will be centered on the image"""
    sequencer = bpy.ops.sequencer
    sequence_editor = bpy.context.scene.sequence_editor
    render = bpy.context.scene.render

    sequences = [s for s in sequences if s.type in ('IMAGE', 'MOVIE')]

    if not sequences:
        return None

    sequencer.select_all(action='DESELECT')

    for s in sequences:
        s.mute = True

        sequence_editor.active_strip = s
        sequencer.effect_strip_add(type='TRANSFORM')

        active = sequence_editor.active_strip
        active.name = "TRANSFORM-%s" % s.name
        active.blend_type = 'ALPHA_OVER'
        active.select = False

    print("Successfully processed " + str(len(sequences)) + " image sequences")
    return True

# def calc_transform_effect_scale(sequence):
#     """Takes a transform effect and returns the scale it should use
#        to preserve the scale of its cropped input"""
#     # if not (sequence or sequence.type == 'TRANSFORM'):
#     #     raise AttributeError

#     s = sequence.input_1

#     crop_x, crop_y = s.elements[0].orig_width - (s.crop.min_x + s.crop.max_x),
#                      s.elements[0].orig_height - (s.crop.min_y + s.crop.max_y)
#     ratio_x, ratio_y = crop_x / render.resolution_x,
#                        crop_y / render.resolution_y
#     if ratio_x > 1 or ratio_y > 1:
#         ratio_x /= ratio_y
#         ratio_y /= ratio_x
#     return ratio_x, ratio_y
#     active.scale_start_x, active.scale_start_y = ratio_x ratio_y


# TODO: make it work
def set_img_strip_offset(sequences):
    """Takes a list of img sequences and changes their parameters"""
    if not sequences:
        raise AttributeError('No sequences passed to the function')

    for s in sequences:
        if s.use_translation and (s.offset_x != 0 or s.offset_y != 0):
            continue

        image_width = s.elements[0].orig_width
        image_height = s.elements[0].orig_height

        if image_width == 0 or image_height == 0:
            continue

        res_x, res_y = render.resolution_x, render.resolution_y

        if image_width < res_x or image_height < res_y:
            s.use_translation = True
            s.transform.offset_x = (res_x - image_width) / 2
            s.transform.offset_y = (res_y - image_height) / 2
    return True
