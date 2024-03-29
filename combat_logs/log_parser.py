#!/usr/bin/python
# Copyright 2010 Matt Rudary
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""Library to parse an eve game log.

It is not unusual for multiple headers to occur in the same log
file. This parser will not catch that, and so may associate events
with the wrong character.

"""

import datetime
import itertools
import re
import sys


class UTC(datetime.tzinfo):
    """UTC"""
    _ZERO = datetime.timedelta(0)

    def utcoffset(self, dt):
        return self._ZERO

    def tzname(self, dt):
        return "UTC"

    def dst(self, dt):
        return self._ZERO


_TIMESTAMP_PATTERN = (
    r'(?P<year>\d{4})\.(?P<month>\d{2})\.(?P<day>\d{2})'
    r' (?P<hour>\d{2}):(?P<min>\d{2}):(?P<sec>\d{2})')


class LogEntry(object):
    """An entry in the log."""
    UNKNOWN = 0
    COMBAT = 1
    INFO = 2
    NOTIFY = 3
    WARNING = 4
    QUESTION = 5
    HINT = 6
    NONE = 7

    def __init__(self, timestamp, entry_type, data):
        self._timestamp = timestamp
        self._entry_type = entry_type
        self._data = data

    @property
    def timestamp(self):
        return self._timestamp

    @property
    def entry_type(self):
        return self._entry_type

    @property
    def data(self):
        return self._data

    _LOG_LINE_RE = re.compile(
        r'^\[ %s \] \((?P<type>[^)]+)\) (?P<data>.+)$'
        % _TIMESTAMP_PATTERN)

    @classmethod
    def parse_line(cls, line, log):
        """Parse the given line and return a LogEntry.

        Returns None if the current line does not start with a timestamp
        and entry type. This usually indicates a continuation of a previous
        message and is usually because multiple lines of text were shown
        to a user.
        """
        m = cls._LOG_LINE_RE.match(line)
        if m is None:
            return None
        entry_type = m.group('type')
        y, mo, d, h, mi, s = map(int, m.group('year', 'month', 'day',
                                              'hour', 'min', 'sec'))
        timestamp = datetime.datetime(y, mo, d, h, mi, s, tzinfo = UTC())
        data = m.group('data')
        if entry_type == 'combat':
            return CombatLogEntry(timestamp, data, log)
        else:
            if entry_type == 'info':
                t = LogEntry.INFO
            elif entry_type == 'notify':
                t = LogEntry.NOTIFY
            elif entry_type == 'warning':
                t = LogEntry.WARNING
            elif entry_type == 'question':
                t = LogEntry.QUESTION
            elif entry_type == 'hint':
                t = LogEntry.HINT
            elif entry_type == 'None':
                t = LogEntry.NONE
            else:
                raise ValueError('Unknown log entry type "%s".' % entry_type)
            return LogEntry(timestamp, t, data)


class CombatLogEntry(LogEntry):
    def __init__(self, timestamp, data, log):
        LogEntry.__init__(self, timestamp, LogEntry.COMBAT, data)
        self._parse_data(log)

    @property
    def target(self):
        """The target of this attack."""
        return self._target

    @property
    def attacker(self):
        """The aggressor in this attack."""
        return self._attacker

    @property
    def weapon(self):
        """The weapon used in this attack."""
        return self._weapon

    @property
    def damage(self):
        """The amount of damage dealt by this attack."""
        return self._damage

    def _parse_data(self, log):
        if log.log_type == Log.V3:
            self._parse_v3()
        elif log.log_type == Log.COMPLEX:
            self._parse_complex()
        elif log.log_type == Log.SIMPLIFIED:
            self._parse_simple()
        else:
            try:
                self._parse_v3()
                log.log_type = Log.V3
            except ValueError:
                try:
                    self._parse_simple()
                    log.log_type = Log.SIMPLIFIED
                except ValueError:
                    self._parse_complex()
                    log.log_type = Log.COMPLEX

    _VERB_PHRASES = [
        '%(attacker)s (?:lightly |heavily )?hits %(target)s, %(damage)s\.$',
        '%(attacker)s misses %(target)s completely\.(?!%(damage)s)$',
        '%(attacker)s aims well at %(target)s, %(damage)s\.$',
        '%(attacker)s barely scratches %(target)s, %(damage)s\.$',
        '%(attacker)s places an excellent hit on %(target)s, %(damage)s\.$',
        ('%(attacker)s lands a hit on %(target)s which glances off,'
         ' %(damage)s\.$'),
        '%(attacker)s is well aimed at %(target)s, %(damage)s\.$',
        '%(attacker)s barely misses %(target)s\.(?!%(damage)s)$',
        '%(attacker)s glances off %(target)s, %(damage)s\.$',
        '%(attacker)s strikes %(target)s perfectly, %(damage)s\.$',
        '%(attacker)s perfectly strikes %(target)s, %(damage)s\.$',
        ]

    _ATTACKER_PATTERNS = [ '(?P<attacker>You)r (?:group of )?(?P<weapon>.*?)',
                            '(?P<weapon>.*?) belonging to (?P<attacker>.*?)',
                            '(?P<attacker>.*?)(?P<weapon>)' ]

    _DAMAGE_PATTERN = r'[^,]*?(?P<damage>\d+\.\d+)?(?:</b>)? damage'

    _VERB_PHRASE_RES = [
        re.compile(vp % { 'attacker': '(?:<color[^>]*>)?%s' % a,
                          'target': '(?P<target>.*?)',
                          'damage': _DAMAGE_PATTERN })
        for vp in _VERB_PHRASES
        for a in _ATTACKER_PATTERNS
        ]

    def _parse_complex(self):
        m = None
        for rex in self._VERB_PHRASE_RES:
            m = rex.match(self._data)
            if m is not None:
                break
        if m is None:
            raise ValueError(
                'Could not parse """%s""" as complex.' % self._data)

        self._target = m.group('target')
        self._attacker = m.group('attacker')
        self._weapon = m.group('weapon')
        damage = m.group('damage')
        if damage is None:
            self._damage = 0
        else:
            self._damage = float(damage)

    _SIMPLIFIED_PHRASES = [
        ('(?:<color[^>]*>)?(?P<attacker>.*) (?:hits|strikes) (?P<target>you) '
         'for %(simple_damage)s$'),
        ('(?:<color[^>]*>)?(?P<weapon>.*) (?:hits|strikes) (?P<target>.*) '
         'for %(simple_damage)s$'),
        '(?:<color[^>]*>)?(?P<attacker>.*) misses (?P<target>you)(?P<damage>)$',
        '(?:<color[^>]*>)?(?P<weapon>.*) misses (?P<target>[^.]*)(?P<damage>)$',
        '(?:<color[^>]*>)?(?P<attacker>.*) miss (?P<target>you)(?P<damage>)$',
        '(?:<color[^>]*>)?(?P<weapon>.*) miss (?P<target>[^.]*)(?P<damage>)$',
        ]

    _SIMPLIFIED_PHRASE_RES = [
        re.compile(sp % {
                'simple_damage': ('<b>(?P<damage>\d+)</b> damage'
                                  '(?: \(Wrecking!\))?') })
        for sp in _SIMPLIFIED_PHRASES
        ]

    def _parse_simple(self):
        m = None
        for rex in self._SIMPLIFIED_PHRASE_RES:
            m = rex.match(self._data)
            if m is not None:
                break
        if m is None:
            raise ValueError('Could not parse """%s""" as simple.' % self._data)

        self._target = m.group('target')
        if self._target == 'you':
            self._attacker = m.group('attacker')
            self._weapon = ''
        else:
            self._attacker = 'You'
            self._weapon = m.group('weapon')
        damage = m.group('damage')
        if damage:
            self._damage = int(damage)
        else:
            self._damage = 0

    _V3_PHRASES = [
        ('<color[^>]*><b>(?P<damage>[0-9]+)'
         '</b> <color[^>]*><font[^>]*>(?P<preposition>.*)</font> '
         '<b><color[^>]*>(?P<object>.*)'
         '</b><font[^>]*><color[^>]*>(?: - (?P<weapon>.*))?'
         ' - (?:Glances Off|Grazes|Hits|Penetrates|Smashes|Wrecks)$'),
        ('(?P<attacker>You)r (?P<weapon>.*) misses (?P<target>.*) completely'
         r' - \2$'),
        '(?P<attacker>.*) misses (?P<target>you) completely$',
        ('<color[^>]*><b>(?P<ew>.*)</b> <color[^>]*><font[^>]*>from</font> '
         '<color[^>]*><b>(?P<attacker>.*)</b> <color[^>]*><font[^>]*>to '
         '<b><color[^>]*></font>(?P<target>.*)!$'),
        ]

    _V3_PHRASE_RES = [re.compile(phrase) for phrase in _V3_PHRASES]

    def _parse_v3(self):
        m = None
        for rex in self._V3_PHRASE_RES:
            m = rex.match(self._data)
            if m is not None:
                break
        if m is None:
            raise ValueError('Could not parse """%s""" as V3' % self._data)

        d = m.groupdict()
        if 'preposition' in d:
            p = d['preposition']
            assert p == 'to' or p == 'from'
            if p == 'to':
                self._target = d['object']
                self._attacker = 'You'
            else:
                self._target = 'you'
                self._attacker = d['object']
        else:
            self._target = d['target']
            if self._target == 'you':
                self._attacker = d['attacker']
            else:
                self._attacker = 'You'

        if self._target == 'you':
            self._weapon = ''
        else:
            self._weapon = d['weapon']

        if 'damage' in d:
            self._damage = int(d['damage'])
        else:
            self._damage = 0


class Log(object):
    # Log types:
    UNKNOWN = 0
    COMPLEX = 1
    SIMPLIFIED = 2
    V3 = 3

    """A log consists of some metadata and a sequence of log entries."""
    def __init__(self, listener, start_time, infile):
        self._listener = listener
        self._start_time = start_time
        self.log_type = Log.UNKNOWN
        self._log_entries = list(itertools.ifilter(
            None,
            (LogEntry.parse_line(l.rstrip(), self) for l in infile)))

    @property
    def listener(self):
        """The character for whom this log was recorded. May be 'Unknown'."""
        return self._listener

    @property
    def start_time(self):
        """A datetime.datetime indicating the time recording started."""
        return self._start_time

    @property
    def log_entries(self):
        """An iterator to a sequence of LogEntry objects in timestamp order."""
        return iter(self._log_entries)

    @property
    def num_entries(self):
        """The number of entries in this log."""
        return len(self._log_entries)

    @classmethod
    def parse_log(cls, log_file):
        """Parse the given log file.

        Args:
          log_file: A filename or file-like object that contains a
              single gamelog. If log_file is a file-like object, it
              will be closed before this function returns.

        Returns:
          A Log object.

        """
        if isinstance(log_file, basestring):
            infile = open(log_file, 'r')
        else:
            infile = log_file

        try:
            listener, timestamp = cls._read_header(infile)
            return Log(listener, timestamp, infile)
        finally:
            infile.close()

    _MINUSES_RE = re.compile('^-+$')
    _GAMELOG_RE = re.compile('Gamelog')
    _LISTENER_RE = re.compile('Listener: (.*)')
    _SESSION_RE = re.compile(
        'Session [Ss]tarted: %s' % _TIMESTAMP_PATTERN)

    @classmethod
    def _read_header(cls, infile):
        try:
            if not cls._MINUSES_RE.match(infile.next().rstrip()):
                raise ValueError('Missing --- line at start of file.')
            if not cls._GAMELOG_RE.search(infile.next().rstrip()):
                raise ValueError('Missing "Gamelog" line in header.')
            # Empty logs don't have listeners...
            maybe_listener_line = infile.next().rstrip()
            m = cls._LISTENER_RE.search(maybe_listener_line)
            if m is None:
                listener = None
                session_start_line = maybe_listener_line
            else:
                listener = m.group(1)
                session_start_line = infile.next().rstrip()
            m = cls._SESSION_RE.search(session_start_line)
            if m is None:
                raise ValueError('Missing "Session started" line in header.')
            y, mo, d, h, mi, s = map(int, m.group('year', 'month', 'day',
                                                  'hour', 'min', 'sec'))
            timestamp = datetime.datetime(y, mo, d, h, mi, s, tzinfo = UTC())
            if not cls._MINUSES_RE.match(infile.next().rstrip()):
                raise ValueError('Missing --- line to end header.')

        except StopIteration:
            raise ValueError('Cannot parse header -- too few lines.')
        return listener, timestamp


if __name__ == '__main__':
    for filename in sys.argv[1:]:
        try:
            log = Log.parse_log(filename)
            print 'Log %s had %d entries.' % (filename, log.num_entries)
        except ValueError, e:
            print >>sys.stderr, 'Error parsing %s: %s.' % (filename, e)

