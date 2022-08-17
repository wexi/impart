#!/usr/bin/env python3
# coding: utf-8

# Builds local KiCad "legacy" component libraries from downloaded
# component zipfiles. Currently assembles just symbols and
# footptints. Tested with KiCad 6.0.7.
# 
# Web sources:
# 
# octopart:       https://octopart.com/ or https://eeconcierge.com/
# samacsys:       https://componentsearchengine.com/
# ultralibrarian: https://www.ultralibrarian.com/
# snapeda:        https://www.snapeda.com/

from mydirs import SRC, LIB     # *CONFIGURE ME*
import argparse
import clipboard
import re
import readline
import shutil
import signal
import zipfile


def Signal(signum, stack):
    raise UserWarning('CTRL-C')


def Xinput(prompt):
    # extended input to allow Emacs input backspace
    reply = input(prompt)
    index = reply.find('~') + 1
    return reply[index:]


class Pretext:
    """input() with inserted text"""
    def __init__(self, pretext):
        self._pretext = pretext
        readline.set_completer(lambda: None)
        readline.set_pre_input_hook(self.insert)
        clipboard.copy('')

    def __call__(self, prompt):
        reply = Xinput(prompt + (': ' if self._pretext else ' [=clipboard]: '))
        if reply == '':
            text = clipboard.paste()
            if text:
                clipboard.copy('')
                self._pretext = text.replace('\n', ' ')
                reply = Xinput(prompt + ': ')
        readline.set_pre_input_hook(None)
        return reply.strip()

    def insert(self):
        readline.insert_text(self._pretext)
        readline.redisplay()


class Select:
    """input() from select completions """
    def __init__(self, select):
        self._select = select
        readline.set_completer(self.complete)
        readline.set_pre_input_hook(None)

    def __call__(self, prompt):
        reply = Xinput(prompt)
        readline.set_completer(lambda: None)
        return reply.strip()

    def complete(self, text, state):
        if state == 0:
            if text:
                self._pre = [s for s in self._select
                             if s and s.startswith(text)]
            else:
                self._pre = self._select[:]

        try:
            echo = self._pre[state]
        except IndexError:
            echo = None

        return echo


PRJ = {0: 'octopart', 1: 'samacsys', 2: 'ultralibrarian', 3: 'snapeda'}


class Catch(Exception):
    def __init__(self, value):
        self.catch = value
        super().__init__(self)


def Zipper(root, suffix):
    """return zipfile.Path starting with root ending with suffix"""
    def zipper(parent):
        if parent.name.endswith(suffix):
            raise Catch(parent)
        elif parent.is_dir():
            for child in parent.iterdir():
                zipper(child)

    try:
        zipper(root)
    except Catch as e:
        return e.catch

    return None


def Impart(zip):
    """zip is a pathlib.Path to import the symbol from"""
    if not zipfile.is_zipfile(zip):
        return None

    device = zip.name[:-4]
    eec = Pretext(device)('Generic device name')
    if eec == '':
        return None

    with zipfile.ZipFile(zip) as zf:
        root = zipfile.Path(zf)

        while True:
            desc = root / 'eec.dcm'
            symb = root / 'eec.lib'
            food = root / 'eec.pretty'
            if desc.exists() and symb.exists() and food.exists():
                prj = 0         # OCTOPART
                break

            dir = Zipper(root, 'KiCad')
            if dir:
                desc = Zipper(dir, '.dcm')
                symb = Zipper(dir, '.lib')
                food = dir
                assert desc and symb, 'Not in samacsys format'
                prj = 1         # SAMACSYS
                break

            dir = root / 'KiCAD'
            if dir.exists():
                desc = Zipper(dir, '.dcm')
                symb = Zipper(dir, '.lib')
                food = Zipper(dir, '.pretty')
                assert symb and food, 'Not in ultralibrarian format'
                prj = 2         # ULTRALIBRARIAN
                break

            symb = Zipper(root, '.lib')
            if symb:
                desc = Zipper(root, '.dcm')
                food = root
                prj = 3         # SNAPEDA
                break

            assert False, 'Unknown library zipfile'

        txt = desc.read_text().splitlines() if desc else [
            '#', '# ' + device, '#', '$CMP ' + eec, 'D', 'F', '$ENDCMP']

        print('Adding', eec, 'to', PRJ[prj])

        stx = None
        etx = None
        hsh = None
        for no, tx in enumerate(txt):
            if stx is None:
                if tx.startswith('#'):
                    if tx.strip() == '#' and hsh is None:
                        hsh = no  # header start
                elif tx.startswith('$CMP '):
                    t = tx[5:].strip()
                    if not t.startswith(eec):
                        return 'Unexpected device in', desc.name
                    txt[no] = tx.replace(t, eec, 1)
                    stx = no
                else:
                    hsh = None
            elif etx is None:
                if tx.startswith('$CMP '):
                    return 'Multiple devices in', desc.name
                elif tx.startswith('$ENDCMP'):
                    etx = no + 1
                elif tx.startswith('D'):
                    t = tx[2:].strip()
                    dsc = Pretext(t)('Device description')
                    if dsc:
                        txt[no] = 'D ' + dsc
                elif tx.startswith('F'):
                    t = tx[2:].strip()
                    url = Pretext(t)('Datasheet URL')
                    if url:
                        txt[no] = 'F ' + url
        if etx is None:
            return eec, 'not found in', desc.name

        rd_dcm = LIB / (PRJ[prj] + '.dcm')
        wr_dcm = LIB / (PRJ[prj] + '.dcm~')
        update = updated = False
        with rd_dcm.open('rt') as rf:
            with wr_dcm.open('wt') as wf:
                for tx in rf:
                    if re.match('# *end ', tx, re.IGNORECASE):
                        if not updated:
                            wf.write('\n'.join(txt[stx if hsh is None else hsh:
                                                   etx]) + '\n')
                        wf.write(tx)
                        break
                    elif tx.startswith('$CMP '):
                        t = tx[5:].strip()
                        if t.startswith(eec):
                            yes = Pretext('Yes')(
                                eec + ' in ' + rd_dcm.name + ', replace it ? ')
                            update = yes and 'yes'.startswith(yes.lower())
                            if not update:
                                return 'OK:', eec, 'already in', rd_dcm.name
                            wf.write('\n'.join(txt[stx:etx]) + '\n')
                            updated = True
                        else:
                            wf.write(tx)
                    elif update:
                        if tx.startswith('$ENDCMP'):
                            update = False
                    else:
                        wf.write(tx)

        txt = symb.read_text().splitlines()

        stx = None
        etx = None
        hsh = None
        for no, tx in enumerate(txt):
            if stx is None:
                if tx.startswith('#'):
                    if tx.strip() == '#' and hsh is None:
                        hsh = no  # header start
                elif tx.startswith('DEF '):
                    t = tx.split()[1]
                    if not t.startswith(eec):
                        return 'Unexpected device in', symb.name
                    txt[no] = tx.replace(t, eec, 1)
                    stx = no
                else:
                    hsh = None
            elif etx is None:
                if tx.startswith('ENDDEF'):
                    etx = no + 1
                elif tx.startswith('F1 '):
                    txt[no] = tx.replace(device, eec, 1)
            elif tx.startswith('DEF '):
                return 'Multiple devices in', symb.name
        if etx is None:
            return device, 'not found in', symb.name

        rd_lib = LIB / (PRJ[prj] + '.lib')
        wr_lib = LIB / (PRJ[prj] + '.lib~')
        update = updated = False
        with rd_lib.open('rt') as rf:
            with wr_lib.open('wt') as wf:
                for tx in rf:
                    if re.match('# *end ', tx, re.IGNORECASE):
                        if not updated:
                            wf.write('\n'.join(txt[stx if hsh is None else hsh:
                                                   etx]) + '\n')
                        wf.write(tx)
                        break
                    elif tx.startswith('DEF '):
                        t = tx.split()[1]
                        if t.startswith(eec):
                            yes = Pretext('Yes')(
                                eec + ' in ' + rd_lib.name + ', replace it ? ')
                            update = yes and 'yes'.startswith(yes.lower())
                            if not update:
                                return 'OK:', eec, 'already in', rd_lib
                            wf.write('\n'.join(txt[stx:etx]) + '\n')
                            updated = True
                        else:
                            wf.write(tx)
                    elif update:
                        if tx.startswith('ENDDEF'):
                            update = False
                    else:
                        wf.write(tx)

        pretty = 0
        for rd in food.iterdir():
            if rd.name.endswith('.kicad_mod') or rd.name.endswith('.mod'):
                pretty += 1
                txt = rd.read_text()
                with (LIB / (PRJ[prj] + '.pretty') / rd.name).open('wt') as wr:
                    wr.write(txt)
        print('footprints:', pretty)

        wr_dcm.replace(rd_dcm)
        wr_lib.replace(rd_lib)

    return 'OK:',


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        epilog='Note, empty input: invites clipboard content, if available.')
    parser.add_argument('--init', action='store_true',
                        help='initialize library')
    parser.add_argument('--zap', action='store_true',
                        help='delete source zipfile after assembly')
    arg = parser.parse_args()

    signal.signal(signal.SIGINT, Signal)

    readline.set_completer_delims('\t')
    readline.parse_and_bind('tab: complete')
    readline.set_auto_history(False)

    try:
        if arg.init:
            libras = list(PRJ.values())
            while libras:
                libra = Select(libras)('Erase/Initialize which library? ')
                if libra == '':
                    break
                assert libra in libras, 'Unknown library'

                dcm = LIB / (libra + '.dcm')
                with dcm.open('wt') as dcmf:
                    dcmf.writelines(['EESchema-DOCLIB  Version 2.0\n',
                                     '#End Doc Library\n'])
                dcm.chmod(0o660)

                lib = LIB / (libra + '.lib')
                with lib.open('wt') as libf:
                    libf.writelines(['EESchema-LIBRARY Version 2.4\n',
                                     '#encoding utf-8\n',
                                     '#End Library\n'])
                lib.chmod(0o660)

                pcb = LIB / (libra + '.pretty')
                shutil.rmtree(pcb, ignore_errors=True)
                pcb.mkdir(mode=0o770, parents=False, exist_ok=False)

                libras.remove(libra)

        while True:
            zips = [zip.name for zip in SRC.glob('*.zip')]
            zip = SRC / Select(zips)('Library zip file: ')
            response = Impart(zip)
            if response:
                print(*response)
                if arg.zap and response[0] == 'OK:':
                    zip.unlink()
    except EOFError:
        print('EOF')
    except Exception as e:
        print(*e.args)
    exit(0)
