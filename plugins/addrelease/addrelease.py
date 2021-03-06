# -*- coding: utf-8 -*-

PLUGIN_NAME = "Add Cluster As Release"
PLUGIN_AUTHOR = 'Frederik "Freso" S. Olesen, Lukáš Lalinský, Philip Jägenstedt'
PLUGIN_DESCRIPTION = "Adds a plugin context menu option to clusters and single\
 files to help you quickly add them as releases or standalone recordings to\
 the MusicBrainz database via the website by pre-populating artists,\
 track names and times."
PLUGIN_VERSION = "0.7.3"
PLUGIN_API_VERSIONS = ["2.0"]

from picard import config, log
from picard.cluster import Cluster
from picard.const import MUSICBRAINZ_SERVERS
from picard.file import File
from picard.util import webbrowser2
from picard.ui.itemviews import BaseAction, register_cluster_action, register_file_action

import os
import tempfile

HTML_HEAD = """<!doctype html>
<meta charset="UTF-8">
<title>%s</title>
<form action="%s" method="post">
"""
HTML_INPUT = """<input type="hidden" name="%s" value="%s">
"""
HTML_TAIL = """<input type="submit" value="%s">
</form>
<script>document.forms[0].submit()</script>
"""
HTML_ATTR_ESCAPE = {
    "&": "&amp;",
    '"': "&quot;"
}


def mbserver_url(path):
    host = config.setting["server_host"]
    port = config.setting["server_port"]
    if host in MUSICBRAINZ_SERVERS or port == 443:
        urlstring = "https://%s%s" % (host, path)
    elif port is None or port == 80:
        urlstring = "http://%s%s" % (host, path)
    else:
        urlstring = "http://%s:%d%s" % (host, port, path)
    return urlstring


class AddObjectAsEntity(BaseAction):
    NAME = "Add Object As Entity..."
    objtype = None
    submit_path = '/'

    def __init__(self):
        super(AddObjectAsEntity, self).__init__()
        self.form_values = {}

    def check_object(self, objs, objtype):
        """
        Checks if a given object array is valid (ie., has one item) and that
        its item is an object of the given type.

        Returns either False (if conditions are not met), or the object in the
        array.
        """
        if not isinstance(objs[0], objtype) or len(objs) != 1:
            return False
        else:
            return objs[0]

    def add_form_value(self, key, value):
        "Add global (e.g., release level) name-value pair."
        self.form_values[key] = value

    def set_form_values(self, objdata):
        return

    def generate_html_file(self, form_values):
        (fd, fp) = tempfile.mkstemp(suffix=".html")

        with os.fdopen(fd, "w", encoding="utf-8") as f:
            def esc(s):
                return "".join(HTML_ATTR_ESCAPE.get(c, c) for c in s)
            # add a global (release-level) name-value

            def nv(n, v):
                f.write(HTML_INPUT % (esc(n), esc(v)))

            f.write(HTML_HEAD % (self.NAME, mbserver_url(self.submit_path)))

            for key in form_values:
                nv(key, form_values[key])

            f.write(HTML_TAIL % (self.NAME))

        return fp

    def open_html_file(self, fp):
        webbrowser2.open("file://" + fp)

    def callback(self, objs):
        objdata = self.check_object(objs, self.objtype)
        try:
            if objdata:
                self.set_form_values(objdata)
                html_file = self.generate_html_file(self.form_values)
                self.open_html_file(html_file)
        finally:
            self.form_values.clear()


class AddClusterAsRelease(AddObjectAsEntity):
    NAME = "Add Cluster As Release..."
    objtype = Cluster
    submit_path = '/release/add'

    def __init__(self):
        super().__init__()
        self.discnumber_shift = -1

    def extract_discnumber(self, metadata):
        """
        >>> from picard.metadata import Metadata
        >>> m = Metadata()
        >>> AddClusterAsRelease().extract_discnumber(m)
        0
        >>> m["discnumber"] = "boop"
        >>> AddClusterAsRelease().extract_discnumber(m)
        0
        >>> m["discnumber"] = "1"
        >>> AddClusterAsRelease().extract_discnumber(m)
        0
        >>> m["discnumber"] = 1
        >>> AddClusterAsRelease().extract_discnumber(m)
        0
        >>> m["discnumber"] = -1
        >>> AddClusterAsRelease().extract_discnumber(m)
        0
        >>> m["discnumber"] = "1/1"
        >>> AddClusterAsRelease().extract_discnumber(m)
        0
        >>> m["discnumber"] = "2/2"
        >>> AddClusterAsRelease().extract_discnumber(m)
        1
        >>> a = AddClusterAsRelease()
        >>> m["discnumber"] = "-2/2"
        >>> a.extract_discnumber(m)
        0
        >>> m["discnumber"] = "-1/4"
        >>> a.extract_discnumber(m)
        1
        >>> m["discnumber"] = "1/4"
        >>> a.extract_discnumber(m)
        3

        """
        # As per https://musicbrainz.org/doc/Development/Release_Editor_Seeding#Tracklists_data
        # the medium numbers ("m") must be starting with 0.
        # Maybe the existing tags don't have disc numbers in them or
        # they're starting with something smaller than or equal to 0, so try
        # to produce a sane disc number.
        try:
            discnumber = metadata.get("discnumber", "1")
            # Split off any totaldiscs information
            discnumber = discnumber.split("/", 1)[0]
            m = int(discnumber)
            if m <= 0:
                # A disc number was smaller than or equal to 0 - all other
                # disc numbers need to be changed to accommodate that.
                self.discnumber_shift = max(self.discnumber_shift, 0 - m)
            m = m + self.discnumber_shift
        except ValueError as e:
            # The most likely reason for an exception at this point is because
            # the disc number in the tags was not a number. Just log the
            # exception and assume the medium number is 0.
            log.info("Trying to get the disc number of %s caused the following error: %s; assuming 0",
                     metadata["~filename"], e)
            m = 0
        return m

    def set_form_values(self, cluster):
        nv = self.add_form_value

        nv("artist_credit.names.0.artist.name", cluster.metadata["albumartist"])
        nv("name", cluster.metadata["album"])

        for i, file in enumerate(cluster.files):
            try:
                i = int(file.metadata["tracknumber"]) - 1
            except:
                pass

            m = self.extract_discnumber(file.metadata)

            # add a track-level name-value
            def tnv(n, v):
                nv("mediums.%d.track.%d.%s" % (m, i, n), v)

            tnv("name", file.metadata["title"])
            if file.metadata["artist"] != cluster.metadata["albumartist"]:
                tnv("artist_credit.names.0.name", file.metadata["artist"])
            tnv("length", str(file.metadata.length))


class AddFileAsRecording(AddObjectAsEntity):
    NAME = "Add File As Standalone Recording..."
    objtype = File
    submit_path = '/recording/create'

    def set_form_values(self, track):
        nv = self.add_form_value
        nv("edit-recording.name", track.metadata["title"])
        nv("edit-recording.artist_credit.names.0.artist.name", track.metadata["artist"])
        nv("edit-recording.length", track.metadata["~length"])


class AddFileAsRelease(AddObjectAsEntity):
    NAME = "Add File As Release..."
    objtype = File
    submit_path = '/release/add'

    def set_form_values(self, track):
        nv = self.add_form_value

        # Main album attributes
        if track.metadata["albumartist"]:
            nv("artist_credit.names.0.artist.name", track.metadata["albumartist"])
        else:
            nv("artist_credit.names.0.artist.name", track.metadata["artist"])
        if track.metadata["album"]:
            nv("name", track.metadata["album"])
        else:
            nv("name", track.metadata["title"])

        # Tracklist
        nv("mediums.0.track.0.name", track.metadata["title"])
        nv("mediums.0.track.0.artist_credit.names.0.name", track.metadata["artist"])
        nv("mediums.0.track.0.length", str(track.metadata.length))


register_cluster_action(AddClusterAsRelease())
register_file_action(AddFileAsRecording())
register_file_action(AddFileAsRelease())

if __name__ == "__main__":
    import doctest
    doctest.testmod()
