import os
import tempfile
import shutil
import json
import pickle

from collections import OrderedDict
from io import BytesIO

import numpy as np
import numpy.testing as npt

import unittest
import unittest.mock as mock

from gulpio.fileio import (GulpChunk,
                           ChunkWriter,
                           GulpIngestor,
                           GulpDirectory,
                           calculate_chunk_slices,
                           json_serializer,
                           pickle_serializer,
                           ImgInfo,
                           )
from gulpio.adapters import AbstractDatasetAdapter


class FSBase(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='fileio-test-')

    def tearDown(self):
        shutil.rmtree(self.temp_dir)


class TestJSONSerializer(FSBase):

    def test_dump(self):
        filename = os.path.join(self.temp_dir, 'ANY_JSON.json')
        content = {'ANY_KEY': 'ANY_CONTENT'}
        json_serializer.dump(content, filename)
        with open(filename, 'r') as fp:
            written_content = json.load(fp)
        self.assertEqual(content, written_content)

    def test_load(self):
        filename = os.path.join(self.temp_dir, 'ANY_JSON.json')
        content = {'ANY_KEY': 'ANY_CONTENT'}
        json_serializer.dump(content, filename)
        received_content = json_serializer.load(filename)
        self.assertEqual(content, received_content)


class TestPickleSerializer(FSBase):

    def test_dump(self):
        filename = os.path.join(self.temp_dir, 'ANY_PICKLE.pickle')
        content = {'ANY_KEY': 'ANY_CONTENT'}
        pickle_serializer.dump(content, filename)
        with open(filename, 'rb') as file_pointer:
            written_content = pickle.load(file_pointer)
        self.assertEqual(content, written_content)

    def test_load(self):
        filename = os.path.join(self.temp_dir, 'ANY_PICKLE.pickle')
        content = {'ANY_KEY': 'ANY_CONTENT'}
        pickle_serializer.dump(content, filename)
        received_content = pickle_serializer.load(filename)
        self.assertEqual(content, received_content)


class TestCalculateChunks(unittest.TestCase):

    def test_one_video_in_chunk(self):
        expected = [slice(0, 1), slice(1, 2)]
        result = calculate_chunk_slices(1, 2)
        self.assertEqual(expected, result)

    def test_two_videos_in_chunk_last_chunk_not_full(self):
        expected = [slice(0, 2), slice(2, 3)]
        result = calculate_chunk_slices(2, 3)
        self.assertEqual(expected, result)

    def test_two_videos_in_chunk_last_chunk_full(self):
        expected = [slice(0, 2), slice(2, 4)]
        result = calculate_chunk_slices(2, 4)
        self.assertEqual(expected, result)

    def test_videos_per_chunk_larger_num_videos(self):
        expected = [slice(0, 2)]
        result = calculate_chunk_slices(100, 2)
        self.assertEqual(expected, result)

    def test_no_videos_in_chunk(self):
        self.assertRaises(AssertionError, calculate_chunk_slices, 0, 1)

    def test_num_videos_is_zero(self):
        self.assertRaises(AssertionError, calculate_chunk_slices, 1, 0)


class GulpChunkElement(FSBase):

    @mock.patch('gulpio.fileio.json_serializer')
    def setUp(self, mock_json_serializer):
        super().setUp()
        self.mock_json_serializer = mock_json_serializer
        self.data_file_path = os.path.join(self.temp_dir, 'ANY_DATA_FILE_PATH')
        self.meta_file_path = os.path.join(self.temp_dir, 'ANY_META_FILE_PATH')
        self.gulp_chunk = GulpChunk(self.data_file_path,
                                    self.meta_file_path,
                                    mock_json_serializer)

    def tearDown(self):
        super().tearDown()


class TestGulpChunk(GulpChunkElement):

    def test_initializer(self):
        self.assertEqual(self.data_file_path,
                         self.gulp_chunk.data_file_path)
        self.assertEqual(self.meta_file_path,
                         self.gulp_chunk.meta_file_path)
        self.assertEqual(self.mock_json_serializer,
                         self.gulp_chunk.serializer)

        self.assertEqual(self.gulp_chunk.meta_dict, OrderedDict())
        self.assertEqual(self.gulp_chunk.fp, None)

    def test_get_or_create_dict_not_exists(self):
        self.assertEqual(self.gulp_chunk.get_or_create_dict(), OrderedDict())

    def test_get_or_create_dict_exists(self):
        open(self.meta_file_path, 'w').close()
        self.gulp_chunk.get_or_create_dict()
        self.mock_json_serializer.load.called_once_with(self.meta_file_path)

    def test_default_factory(self):
        expected = {'meta_data': [], 'frame_info': []}
        self.assertEqual(expected, self.gulp_chunk.default_factory())

    def test_open_with_wb(self):
        with mock.patch('builtins.open', new_callable=mock.mock_open()) as m:
            with self.gulp_chunk.open('wb'):
                m.assert_called_once_with(
                    self.gulp_chunk.data_file_path, 'wb')

    def test_open_with_rb(self):
        with mock.patch('builtins.open', new_callable=mock.mock_open()) as m:
            with self.gulp_chunk.open('rb'):
                m.assert_called_once_with(
                    self.gulp_chunk.data_file_path, 'rb')

    def test_open_with_ab(self):
        with mock.patch('builtins.open', new_callable=mock.mock_open()) as m:
            with self.gulp_chunk.open('ab'):
                m.assert_called_once_with(
                    self.gulp_chunk.data_file_path, 'ab')

    def test_open_unknown_flag(self):
        get_mock = mock.Mock()
        self.gulp_chunk.get_or_create_dict = get_mock
        with self.assertRaises(NotImplementedError):
            with self.gulp_chunk.open('NO_SUCH_FLAG'):
                pass

    def test_flush(self):
        self.gulp_chunk.serializer = json_serializer
        self.gulp_chunk.meta_dict = {'0': {'meta_data': []}}
        self.gulp_chunk.fp = mock.Mock()
        self.gulp_chunk.flush()
        meta_path_written = open(self.meta_file_path).read()
        self.assertEqual('{"0": {"meta_data": []}}', meta_path_written)
        self.gulp_chunk.fp.flush.assert_called_once_with()

    def test_append_meta(self):
        self.gulp_chunk.meta_dict = {'0': {'meta_data': []}}
        self.gulp_chunk.append_meta(0, {'meta': 'ANY_META'})
        expected = {'0': {'meta_data': [{'meta': 'ANY_META'}]}}
        self.assertEqual(expected, self.gulp_chunk.meta_dict)

    def test_append_meta_initializes_correctly(self):
        self.gulp_chunk.meta_dict = {}
        self.gulp_chunk.append_meta(0, {'meta': 'ANY_META'})
        expected = {'0': {'meta_data': [{'meta': 'ANY_META'}],
                          'frame_info': []}}
        self.assertEqual(expected, self.gulp_chunk.meta_dict)

    def test_pad_image(self):
        self.assertEqual(0, GulpChunk.pad_image(0))
        self.assertEqual(1, GulpChunk.pad_image(3))
        self.assertEqual(2, GulpChunk.pad_image(2))
        self.assertEqual(3, GulpChunk.pad_image(1))
        self.assertEqual(0, GulpChunk.pad_image(4))

    def test_write_frame(self):
        bio = BytesIO()
        self.gulp_chunk.meta_dict = {'0': {'meta_data': [{'test': 'ANY'}],
                                           'frame_info': [[1, 2, 3]]}}
        self.gulp_chunk.fp = bio
        with mock.patch('cv2.imencode') as imencode_mock:
            imencode_mock.return_value = '', np.ones((1,), dtype='uint8')
            self.gulp_chunk.write_frame(0, None)
            self.assertEqual(b'\x01\x00\x00\x00', bio.getvalue())
            expected = {'0': {'meta_data': [{'test': 'ANY'}],
                              'frame_info': [[1, 2, 3], ImgInfo(0, 3, 4)]}}
            self.assertEqual(expected, self.gulp_chunk.meta_dict)

    def test_write_frame_new_entry(self):
        bio = BytesIO()
        self.gulp_chunk.meta_dict = {}
        self.gulp_chunk.fp = bio
        with mock.patch('cv2.imencode') as imencode_mock:
            imencode_mock.return_value = '', np.ones((1,), dtype='uint8')
            self.gulp_chunk.write_frame(0, None)
            self.assertEqual(b'\x01\x00\x00\x00', bio.getvalue())
            expected = {'0': {'meta_data': [],
                              'frame_info': [ImgInfo(0, 3, 4)]}}
            self.assertEqual(expected, self.gulp_chunk.meta_dict)

    def test_retrieve_meta_infos(self):
        self.gulp_chunk.meta_dict = {'0': {'meta_data': [{'meta': 'ANY_META'}],
                                           'frame_info': [[1, 2, 3]]}}
        with mock.patch('gulpio.fileio.GulpChunk.open'):
            output = self.gulp_chunk.retrieve_meta_infos('0')
        expected = ([ImgInfo(loc=1, pad=2, length=3)], {'meta': 'ANY_META'})
        self.assertEqual(expected, output)

    def test_id_in_chunk(self):
        self.gulp_chunk.meta_dict = {'0': {'meta_data': [{}],
                                           'frame_info': []}}
        with mock.patch('gulpio.fileio.GulpChunk.open'):
            output = self.gulp_chunk.id_in_chunk(0)
        self.assertTrue(output)

    def test_id_not_in_chunk(self):
        self.gulp_chunk.meta_dict = {'0': {'meta_data': [{}],
                                           'frame_info': []}}
        with mock.patch('gulpio.fileio.GulpChunk.open'):
            output = self.gulp_chunk.id_in_chunk(1)
        self.assertFalse(output)

    def test_read_frames(self):
        # use 'write_frame' to write a single image
        self.gulp_chunk.meta_dict = OrderedDict()
        self.gulp_chunk.fp = BytesIO()
        image = np.ones((3, 3, 3), dtype='uint8')
        self.gulp_chunk.write_frame(0, image)
        self.gulp_chunk.meta_dict['0']['meta_data'].append({})

        # recover the single frame using 'read'
        frames, meta = self.gulp_chunk.read_frames('0')
        npt.assert_array_equal(image, np.array(frames[0]))
        self.assertEqual({}, meta)

    def test_read_all(self):
        read_mock = mock.Mock()
        read_mock.return_value = [], []
        self.gulp_chunk.meta_dict = OrderedDict((('0', {}),
                                                 ('1', {}),
                                                 ('2', {})))
        self.gulp_chunk.read_frames = read_mock
        [_ for _ in self.gulp_chunk.read_all()]
        read_mock.assert_has_calls([mock.call('0'),
                                    mock.call('1'),
                                    mock.call('2')])


class ChunkWriterElement(FSBase):

    def setUp(self):
        super().setUp()
        self.adapter = mock.MagicMock()
        self.adapter.__len__.return_value = 1
        self.output_folder = os.path.join(self.temp_dir, 'ANY_OUTPUT_FOLDER')
        self.videos_per_chunk = 1
        self.chunk_writer = ChunkWriter(self.adapter)

    def tearDown(self):
        pass


class TestChunkWriter(ChunkWriterElement):

    def test_initialization(self):
        self.assertEqual(self.adapter,
                         self.chunk_writer.adapter)

    @mock.patch('gulpio.fileio.GulpChunk')
    def test_write_chunk(self, mock_gulp):
        def mock_iter_data(input_slice):
            yield {'id': 0,
                   'meta': {'meta': 'ANY_META'},
                   'frames': ['ANY_FRAME1', 'ANY_FRAME2'],
                   }
        self.adapter.iter_data = mock_iter_data
        self.chunk_writer.write_chunk(mock_gulp, slice(0, 1))
        mock_gulp.write_frame.assert_has_calls(
            [mock.call(0, 'ANY_FRAME1'),
             mock.call(0, 'ANY_FRAME2')]
        )


class GulpIngestorElement(FSBase):

    @mock.patch('gulpio.adapters.AbstractDatasetAdapter')
    def setUp(self, mock_adapter):
        super().setUp()
        self.adapter = mock_adapter
        self.output_folder = os.path.join(self.temp_dir, 'ANY_OUTPUT_FOLDER')
        self.videos_per_chunk = 1
        self.num_workers = 1
        self.gulp_ingestor = GulpIngestor(self.adapter,
                                          self.output_folder,
                                          self.videos_per_chunk,
                                          self.num_workers)


class TestGulpIngestor(GulpIngestorElement):

    def test_initialization(self):
        self.assertEqual(self.adapter, self.gulp_ingestor.adapter)
        self.assertEqual(self.output_folder, self.gulp_ingestor.output_folder)
        self.assertEqual(self.videos_per_chunk,
                         self.gulp_ingestor.videos_per_chunk)
        self.assertEqual(self.num_workers, self.gulp_ingestor.num_workers)

    @mock.patch('gulpio.utils.ensure_output_dir_exists')
    @mock.patch('gulpio.fileio.ChunkWriter')
    @mock.patch('gulpio.fileio.ProcessPoolExecutor')
    def test_ingest(self,
                    mock_process_pool,
                    mock_chunk_writer,
                    mock_ensure_output_dir):

        # The next three lines mock the ProcessPoolExecutor and it's map
        # function.
        executor_mock = mock.Mock()
        executor_mock.map.return_value = []
        mock_process_pool.return_value.__enter__.return_value = executor_mock
        self.gulp_ingestor.adapter.__len__.return_value = 2
        self.gulp_ingestor()
        mock_chunk_writer.assert_called_once_with(self.adapter)

        executor_mock.map.assert_called_once_with(
            mock_chunk_writer.return_value.write_chunk,
            mock.ANY,
            [slice(0, 1), slice(1, 2)],
        )


class RoundTripAdapter(AbstractDatasetAdapter):

    def __init__(self):
        self.result1 = {
            'meta': {'name': 'empty video'},
            'frames': [],
            'id': 0,
        }
        self.result2 = {
            'meta': {'name': 'bunch of numpy arrays'},
            'frames': [
                np.ones((4, 1, 3), dtype='uint8'),
                np.ones((3, 1, 3), dtype='uint8'),
                np.ones((2, 1, 3), dtype='uint8'),
                np.ones((1, 1, 3), dtype='uint8'),
            ],
            'id': 1,
        }

    def __len__(self):
        return 2

    def iter_data(self, slice_element=None):
        yield self.result1
        yield self.result2


class TestGulpDirectory(FSBase):

    def test_round_trip(self):
        # first, write some garbage in
        adapter = RoundTripAdapter()
        output_directory = os.path.join(self.temp_dir, "ANY_OUTPUT_DIR")
        ingestor = GulpIngestor(adapter, output_directory, 2, 1)
        ingestor()

        # then, read it and make sure the garbage came back out
        gulp_directory = GulpDirectory(output_directory)
        gulp_chunk = next(gulp_directory.chunks())
        expected_output_shapes = [[(4, 1, 3),
                                   (3, 1, 3),
                                   (2, 1, 3),
                                   (1, 1, 3)]
                                  ]
        expected_meta = [{'name': 'bunch of numpy arrays'}]
        with gulp_chunk.open('rb'):
            for i, (frames, meta) in enumerate(gulp_chunk.read_all()):
                self.assertEqual(expected_meta[i], meta)
                self.assertEqual(expected_output_shapes[i],
                                 [np.array(f).shape for f in frames])

        # check that random_access works
        expected_frames = [
            np.ones((4, 1, 3), dtype='uint8'),
            np.ones((3, 1, 3), dtype='uint8'),
            np.ones((2, 1, 3), dtype='uint8'),
            np.ones((1, 1, 3), dtype='uint8'),
        ]
        received_frames, received_meta = gulp_directory[1]
        for ef, rf in zip(expected_frames, received_frames):
            npt.assert_array_equal(ef, np.array(rf))
        self.assertEqual(expected_meta[0], received_meta)

        # now append/extend the gulps
        GulpIngestor(RoundTripAdapter(), output_directory, 2, 1)()

        # then, read it again
        gulp_directory = GulpDirectory(output_directory)
        gulp_chunk = next(gulp_directory.chunks())
        expected_output_shapes = [(4, 1, 3),
                                  (3, 1, 3),
                                  (2, 1, 3),
                                  (1, 1, 3)]
        expected_meta = {'name': 'bunch of numpy arrays'}

        with gulp_chunk.open('rb'):
            for frames, meta in gulp_chunk.read_all():
                self.assertEqual(expected_meta, meta)
                self.assertEqual(expected_output_shapes,
                                 [np.array(f).shape for f in frames])