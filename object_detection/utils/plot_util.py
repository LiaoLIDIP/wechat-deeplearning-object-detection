import os

import numpy as np
import tensorflow as tf
import argparse
import json

from PIL import Image
from object_detection.utils import ops as utils_ops, label_map_util, visualization_utils as vis_util


def load_image_into_numpy_array(img):
    (im_width, im_height) = img.size
    return np.array(img.getdata()).reshape(
        (im_height, im_width, 3)).astype(np.uint8)


def run_inference_for_single_image(img, graph):
    with graph.as_default():
        with tf.Session() as sess:
            # Get handles to input and output tensors
            ops = tf.get_default_graph().get_operations()
            all_tensor_names = {output.name for op in ops for output in op.outputs}
            tensor_dict = {}
            for key in [
                'num_detections', 'detection_boxes', 'detection_scores',
                'detection_classes', 'detection_masks'
            ]:
                tensor_name = key + ':0'

                if tensor_name in all_tensor_names:
                    tensor_dict[key] = tf.get_default_graph().get_tensor_by_name(tensor_name)

            if 'detection_masks' in tensor_dict:
                # The following processing is only for single image
                detection_boxes = tf.squeeze(tensor_dict['detection_boxes'], [0])
                detection_masks = tf.squeeze(tensor_dict['detection_masks'], [0])
                # Reframe is required to translate mask from box coordinates to image coordinates and fit the image size.
                real_num_detection = tf.cast(tensor_dict['num_detections'][0], tf.int32)
                detection_boxes = tf.slice(detection_boxes, [0, 0], [real_num_detection, -1])
                detection_masks = tf.slice(detection_masks, [0, 0, 0], [real_num_detection, -1, -1])
                detection_masks_reframed = utils_ops.reframe_box_masks_to_image_masks(
                    detection_masks, detection_boxes, img.shape[0], img.shape[1])
                detection_masks_reframed = tf.cast(tf.greater(detection_masks_reframed, 0.5), tf.uint8)
                # Follow the convention by adding back the batch dimension
                tensor_dict['detection_masks'] = tf.expand_dims(detection_masks_reframed, 0)

            image_tensor = tf.get_default_graph().get_tensor_by_name('image_tensor:0')

            # Run inference
            output_dict = sess.run(tensor_dict, feed_dict={image_tensor: np.expand_dims(img, 0)})

            # all outputs are float32 numpy arrays, so convert types as appropriate
            output_dict['num_detections'] = int(output_dict['num_detections'][0])
            output_dict['detection_classes'] = output_dict['detection_classes'][0].astype(np.uint8)
            output_dict['detection_boxes'] = output_dict['detection_boxes'][0]
            output_dict['detection_scores'] = output_dict['detection_scores'][0]

            if 'detection_masks' in output_dict:
                output_dict['detection_masks'] = output_dict['detection_masks'][0]

            return output_dict


def load_detection_graph(path_to_checkpoint):
    detection_graph = tf.Graph()
    with detection_graph.as_default():
        od_graph_def = tf.GraphDef()
        with tf.gfile.GFile(path_to_checkpoint, 'rb') as fid:
            serialized_graph = fid.read()
            od_graph_def.ParseFromString(serialized_graph)
            tf.import_graph_def(od_graph_def, name='')
    return detection_graph


def load_category_index(path_to_labels, number_of_classes):
    # Load label map
    label_map = label_map_util.load_labelmap(path_to_labels)
    categories = label_map_util.convert_label_map_to_categories(label_map,
                                                                max_num_classes=number_of_classes,
                                                                use_display_name=True)
    category_index = label_map_util.create_category_index(categories)
    return category_index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Performs detection over input image given a trained detector.')
    parser.add_argument('--inference_graph', dest='inference_graph', type=str, required=True,
                        help='Path to the frozen inference graph.')
    parser.add_argument('--label_map', dest='label_map', type=str, default="mapping_all_classes.txt",
                        help='Path to the label map, which is json-file that maps each category name '
                             'to a unique number.')
    parser.add_argument('--input_image', dest='input_image', type=str, required=True, help='Path to the input image.')
    parser.add_argument('--output_image', dest='output_image', type=str, default='detection.jpg',
                        help='Path to the output image.')
    parser.add_argument('--detection_thresh', dest='detection_thresh', type=float, default=0.4,
                        help='Minimum score threshold for a box to be visualized.')
    args = parser.parse_args()

    # Uncomment the next line on Windows to run the evaluation on the CPU
    os.environ['CUDA_VISIBLE_DEVICES'] = '-1'

    # Path to frozen detection graph. This is the actual model that is used for the object detection.
    path_to_frozen_inference_graph = args.inference_graph
    path_to_labels = args.label_map
    number_of_classes = 999999
    input_image = args.input_image
    output_image = args.output_image
    detection_thresh = args.detection_thresh

    # Read frozen graph
    detection_graph = load_detection_graph(path_to_frozen_inference_graph)
    category_index = load_category_index(path_to_labels, number_of_classes)

    image = Image.open(input_image).convert("RGB")

    # the array based representation of the image will be used later in order to prepare the
    # result image with boxes and labels on it.
    image_np = load_image_into_numpy_array(image)

    # Actual detection.
    output_dict = run_inference_for_single_image(image_np, detection_graph)

    # Visualization of the results of a detection.
    vis_util.visualize_boxes_and_labels_on_image_array(
        image_np,
        output_dict['detection_boxes'],
        output_dict['detection_classes'],
        output_dict['detection_scores'],
        category_index,
        instance_masks=output_dict.get('detection_masks'),
        use_normalized_coordinates=True,
        line_thickness=2,
        min_score_thresh=detection_thresh)
    Image.fromarray(image_np).save(output_image)

    print(output_dict['detection_scores'])

    output_dict['detection_boxes'] = output_dict['detection_boxes'].tolist()
    output_dict['detection_classes'] = output_dict['detection_classes'].tolist()
    output_dict['detection_scores'] = output_dict['detection_scores'].tolist()
    output_with_no_extension = output_image.split('.', 1)[0]
    output_json = ''.join([output_with_no_extension, '.json'])
    json.dump(output_dict, open(output_json, 'w'))
