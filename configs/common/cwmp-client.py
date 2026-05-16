#!/usr/bin/env python3
import base64
import datetime as dt
import json
import os
import pathlib
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"
SOAP_ENC = "http://schemas.xmlsoap.org/soap/encoding/"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
XSD = "http://www.w3.org/2001/XMLSchema"
CWMP = "urn:dslforum-org:cwmp-1-0"

for prefix, uri in {
    "soap-env": SOAP_ENV,
    "soap-enc": SOAP_ENC,
    "xsi": XSI,
    "xsd": XSD,
    "cwmp": CWMP,
}.items():
    ET.register_namespace(prefix, uri)


def utc_now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_output(*args):
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=True)
        return proc.stdout.strip()
    except Exception:
        return ""


def first_ipv4_address(interface):
    output = run_output("ip", "-4", "-o", "addr", "show", "dev", interface)
    for line in output.splitlines():
        parts = line.split()
        if "inet" in parts:
            return parts[parts.index("inet") + 1].split("/")[0]
    return ""


class CWMPState:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.data = {
            "first_boot": True,
            "serial": os.environ.get("CWMP_SERIAL", socket.gethostname().upper()),
            "parameter_values": {},
            "connection_request_count": 0,
            "boot_count": 0,
            "last_download": "",
            "software_version": os.environ.get("CWMP_SOFTWARE_VERSION", "lab-cwmp-client/1.0"),
        }
        self.load()

    def load(self):
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text()))
            except Exception:
                pass

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True))


class ParameterStore:
    def __init__(self, state):
        self.state = state
        self.host = socket.gethostname()
        self.connection_request_port = int(os.environ.get("CWMP_CONNECTION_REQUEST_PORT", "7548"))
        self.ppp_username = os.environ.get("CPE_PPP_USERNAME", "unknown")
        self.lan_address = os.environ.get("CPE_LAN_ADDRESS", "192.168.1.1/24").split("/")[0]
        self.serial = state.data["serial"]
        self.manufacturer = os.environ.get("CWMP_MANUFACTURER", "Containerlab Labs")
        self.oui = os.environ.get("CWMP_OUI", "AC1AB2")
        self.product_class = os.environ.get("CWMP_PRODUCT_CLASS", "ContainerCPE")
        self.hardware_version = os.environ.get("CWMP_HARDWARE_VERSION", "v1")
        self.connection_request_username = os.environ.get("CWMP_CONNECTION_REQUEST_USERNAME", "cwmp")
        self.connection_request_password = os.environ.get("CWMP_CONNECTION_REQUEST_PASSWORD", "cwmp")
        self._start_time = time.time()
        self.root_templates = self._build_templates()

    def _build_templates(self):
        acs_url = os.environ.get("CPE_ACS_URL", "http://genieacs:7547/")
        interval = int(os.environ.get("CPE_PERIODIC_INFORM_INTERVAL", "60"))
        templates = {
            "Device.DeviceInfo.Manufacturer": ("string", False, lambda: self.manufacturer),
            "Device.DeviceInfo.OUI": ("string", False, lambda: self.oui),
            "Device.DeviceInfo.ProductClass": ("string", False, lambda: self.product_class),
            "Device.DeviceInfo.SerialNumber": ("string", False, lambda: self.serial),
            "Device.DeviceInfo.SoftwareVersion": ("string", True, lambda: self.state.data["software_version"]),
            "Device.DeviceInfo.HardwareVersion": ("string", False, lambda: self.hardware_version),
            "Device.ManagementServer.URL": ("string", True, lambda: self.state.data["parameter_values"].get("Device.ManagementServer.URL", acs_url)),
            "Device.ManagementServer.Username": ("string", True, lambda: self.state.data["parameter_values"].get("Device.ManagementServer.Username", "")),
            "Device.ManagementServer.Password": ("string", True, lambda: self.state.data["parameter_values"].get("Device.ManagementServer.Password", "")),
            "Device.ManagementServer.ConnectionRequestURL": ("string", False, self.connection_request_url),
            "Device.ManagementServer.ConnectionRequestUsername": ("string", True, lambda: self.state.data["parameter_values"].get("Device.ManagementServer.ConnectionRequestUsername", self.connection_request_username)),
            "Device.ManagementServer.ConnectionRequestPassword": ("string", True, lambda: self.state.data["parameter_values"].get("Device.ManagementServer.ConnectionRequestPassword", self.connection_request_password)),
            "Device.ManagementServer.PeriodicInformEnable": ("boolean", True, lambda: self.state.data["parameter_values"].get("Device.ManagementServer.PeriodicInformEnable", True)),
            "Device.ManagementServer.PeriodicInformInterval": ("unsignedInt", True, lambda: self.state.data["parameter_values"].get("Device.ManagementServer.PeriodicInformInterval", interval)),
            "Device.ManagementServer.PeriodicInformTime": ("dateTime", True, lambda: self.state.data["parameter_values"].get("Device.ManagementServer.PeriodicInformTime", "0001-01-01T00:00:00Z")),
            "Device.ManagementServer.ConnectionRequestAttempts": ("unsignedInt", False, lambda: self.state.data["connection_request_count"]),
            "Device.IP.Interface.1.Name": ("string", False, lambda: "eth1"),
            "Device.IP.Interface.1.Enable": ("boolean", False, lambda: True),
            "Device.IP.Interface.1.IPv4Address.1.IPAddress": ("string", False, self.ppp_address),
            "Device.LAN.IPAddress": ("string", False, lambda: self.lan_address),
            "Device.DeviceInfo.UpTime": ("unsignedInt", False, lambda: int(time.time() - self._start_time)),
            "Device.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.Username": ("string", False, lambda: self.ppp_username),
            "Device.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.ExternalIPAddress": ("string", False, self.ppp_address),
            "Device.LANDevice.1.WLANConfiguration.1.Enable": ("boolean", True, lambda: self.state.data["parameter_values"].get("Device.LANDevice.1.WLANConfiguration.1.Enable", True)),
            "Device.LANDevice.1.WLANConfiguration.1.SSID": ("string", True, lambda: self.state.data["parameter_values"].get("Device.LANDevice.1.WLANConfiguration.1.SSID", f"ISP-CPE-{self.serial}")),
            "Device.LANDevice.1.WLANConfiguration.1.Channel": ("unsignedInt", True, lambda: int(self.state.data["parameter_values"].get("Device.LANDevice.1.WLANConfiguration.1.Channel", 6))),
            "Device.LANDevice.1.WLANConfiguration.1.Standard": ("string", False, lambda: "802.11n"),
            "Device.LANDevice.1.WLANConfiguration.1.BSSID": ("string", False, lambda: "00:1A:2B:3C:4D:5E"),
            "Device.LANDevice.1.Hosts.HostNumberOfEntries": ("unsignedInt", False, lambda: int(self.state.data["parameter_values"].get("Device.LANDevice.1.Hosts.HostNumberOfEntries", 1))),
        }
        mirrored = {}
        for key, value in templates.items():
            if key.startswith("Device."):
                mirrored["InternetGatewayDevice." + key[len("Device."):]] = value
        templates.update(mirrored)
        return templates

    def connection_request_url(self):
        host_ip = first_ipv4_address("eth0") or self.host
        return f"http://{host_ip}:{self.connection_request_port}/"

    def ppp_address(self):
        return first_ipv4_address("ppp0")

    def parameter_names(self):
        names = set(self.root_templates.keys())
        for full_name in list(names):
            parts = full_name.split(".")
            current = []
            for part in parts[:-1]:
                current.append(part)
                names.add(".".join(current) + ".")
        names.add("Device.")
        names.add("InternetGatewayDevice.")
        return sorted(names)

    def get_value(self, name):
        meta = self.root_templates.get(name)
        if not meta:
            return None
        value_type, _, getter = meta
        value = getter()
        return value_type, value

    def is_writable(self, name):
        meta = self.root_templates.get(name)
        return bool(meta and meta[1])

    def set_value(self, name, value):
        if not self.is_writable(name):
            return False
        if name.endswith("SoftwareVersion"):
            self.state.data["software_version"] = value
        else:
            self.state.data["parameter_values"][name] = value
        self.state.save()
        return True


class CWMPClient:
    def __init__(self):
        self.state = CWMPState(os.environ.get("CWMP_STATE_FILE", "/var/lib/cwmp-client/state.json"))
        self.parameters = ParameterStore(self.state)
        self.inform_now = threading.Event()
        self.stop_event = threading.Event()
        self.cookie_jar = urllib.request.HTTPCookieProcessor()
        self.opener = urllib.request.build_opener(self.cookie_jar)
        self.acs_url = os.environ.get("CPE_ACS_URL", "http://genieacs:7547/")
        self.pending_events = []
        self.pending_boot = False
        self.rpc_methods = [
            "Inform",
            "GetRPCMethods",
            "GetParameterNames",
            "GetParameterValues",
            "SetParameterValues",
            "GetParameterAttributes",
            "SetParameterAttributes",
            "Download",
            "Reboot",
            "FactoryReset",
        ]

    def build_envelope(self, body_element=None, cwmp_id=None):
        envelope = ET.Element(ET.QName(SOAP_ENV, "Envelope"))
        envelope.set(ET.QName(SOAP_ENV, "encodingStyle"), SOAP_ENC)
        header = ET.SubElement(envelope, ET.QName(SOAP_ENV, "Header"))
        id_elem = ET.SubElement(header, ET.QName(CWMP, "ID"))
        id_elem.set(ET.QName(SOAP_ENV, "mustUnderstand"), "1")
        id_elem.text = cwmp_id or f"{int(time.time())}"
        hold = ET.SubElement(header, ET.QName(CWMP, "HoldRequests"))
        hold.text = "0"
        body = ET.SubElement(envelope, ET.QName(SOAP_ENV, "Body"))
        if body_element is not None:
            body.append(body_element)
        return ET.tostring(envelope, encoding="utf-8", xml_declaration=True)

    def build_inform(self, events):
        inform = ET.Element(ET.QName(CWMP, "Inform"))
        device_id = ET.SubElement(inform, "DeviceId")
        for tag, value in (
            ("Manufacturer", self.parameters.manufacturer),
            ("OUI", self.parameters.oui),
            ("ProductClass", self.parameters.product_class),
            ("SerialNumber", self.parameters.serial),
        ):
            elem = ET.SubElement(device_id, tag)
            elem.text = value

        event_list = ET.SubElement(inform, "Event")
        event_list.set(ET.QName(SOAP_ENC, "arrayType"), f"cwmp:EventStruct[{len(events)}]")
        for code in events:
            event = ET.SubElement(event_list, "EventStruct")
            code_elem = ET.SubElement(event, "EventCode")
            code_elem.text = code
            command_key = ET.SubElement(event, "CommandKey")
            command_key.text = ""

        max_env = ET.SubElement(inform, "MaxEnvelopes")
        max_env.text = "1"
        current_time = ET.SubElement(inform, "CurrentTime")
        current_time.text = utc_now()
        retry = ET.SubElement(inform, "RetryCount")
        retry.text = "0"

        params = [
            ("Device.DeviceInfo.SoftwareVersion", *self.parameters.get_value("Device.DeviceInfo.SoftwareVersion")),
            ("Device.DeviceInfo.UpTime", *self.parameters.get_value("Device.DeviceInfo.UpTime")),
            ("Device.ManagementServer.ConnectionRequestURL", *self.parameters.get_value("Device.ManagementServer.ConnectionRequestURL")),
            ("Device.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.ExternalIPAddress", *self.parameters.get_value("Device.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.ExternalIPAddress")),
            ("Device.LANDevice.1.WLANConfiguration.1.SSID", *self.parameters.get_value("Device.LANDevice.1.WLANConfiguration.1.SSID")),
        ]
        parameter_list = ET.SubElement(inform, "ParameterList")
        parameter_list.set(ET.QName(SOAP_ENC, "arrayType"), f"cwmp:ParameterValueStruct[{len(params)}]")
        for name, value_type, value in params:
            item = ET.SubElement(parameter_list, "ParameterValueStruct")
            name_elem = ET.SubElement(item, "Name")
            name_elem.text = name
            value_elem = ET.SubElement(item, "Value")
            value_elem.set(ET.QName(XSI, "type"), f"xsd:{self.xsd_type(value_type)}")
            value_elem.text = self.serialize_value(value_type, value)

        return inform

    def xsd_type(self, value_type):
        return {
            "boolean": "boolean",
            "unsignedInt": "unsignedInt",
            "dateTime": "dateTime",
            "int": "int",
        }.get(value_type, "string")

    def serialize_value(self, value_type, value):
        if value_type == "boolean":
            return "1" if value else "0"
        return "" if value is None else str(value)

    def parse_value(self, value_type, text):
        text = text or ""
        if value_type == "boolean":
            return text in {"1", "true", "True"}
        if value_type in {"unsignedInt", "int"}:
            return int(text or "0")
        return text

    def extract_method(self, xml_bytes):
        if not xml_bytes:
            return None, None, None
        root = ET.fromstring(xml_bytes)
        cwmp_id = root.findtext(f".//{{{CWMP}}}ID")
        body = root.find(f".//{{{SOAP_ENV}}}Body")
        if body is None or not list(body):
            return cwmp_id, None, None
        child = list(body)[0]
        return cwmp_id, child.tag.split("}", 1)[-1], child

    def post(self, body=None):
        headers = {}
        data = None
        if body is not None:
            data = body
            headers["Content-Type"] = 'text/xml; charset="utf-8"'
        request = urllib.request.Request(self.acs_url, data=data, headers=headers, method="POST")
        with self.opener.open(request, timeout=15) as response:
            return response.status, response.read()

    def maybe_session(self, events):
        try:
            status, response = self.post(self.build_envelope(self.build_inform(events)))
            if status >= 400:
                return
            self.handle_server_message(response)
            while True:
                status, response = self.post(None)
                if status == 204 or not response:
                    return
                if not self.handle_server_message(response):
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            print(f"[cwmp] session failed: {exc}", flush=True)
        except Exception as exc:
            print(f"[cwmp] unexpected error: {exc}", flush=True)

    def handle_server_message(self, response):
        cwmp_id, method, element = self.extract_method(response)
        if not method:
            return False
        if method == "InformResponse":
            return True
        response_body = self.dispatch_method(method, element)
        status, follow_up = self.post(self.build_envelope(response_body, cwmp_id=cwmp_id))
        if status == 204 or not follow_up:
            return False
        next_id, next_method, next_element = self.extract_method(follow_up)
        if next_method:
            next_response = self.dispatch_method(next_method, next_element)
            self.post(self.build_envelope(next_response, cwmp_id=next_id))
        return False

    def dispatch_method(self, method, element):
        print(f"[cwmp] received {method}", flush=True)
        handler = getattr(self, f"handle_{method}", None)
        if handler is None:
            return self.simple_fault("9000", f"Method not supported: {method}")
        return handler(element)

    def simple_fault(self, code, message):
        fault = ET.Element(ET.QName(SOAP_ENV, "Fault"))
        ET.SubElement(fault, "faultcode").text = "Client"
        ET.SubElement(fault, "faultstring").text = "CWMP fault"
        detail = ET.SubElement(fault, "detail")
        cwmp_fault = ET.SubElement(detail, ET.QName(CWMP, "Fault"))
        ET.SubElement(cwmp_fault, "FaultCode").text = str(code)
        ET.SubElement(cwmp_fault, "FaultString").text = message
        return fault

    def handle_GetRPCMethods(self, _element):
        response = ET.Element(ET.QName(CWMP, "GetRPCMethodsResponse"))
        method_list = ET.SubElement(response, "MethodList")
        method_list.set(ET.QName(SOAP_ENC, "arrayType"), f"xsd:string[{len(self.rpc_methods)}]")
        for name in self.rpc_methods:
            ET.SubElement(method_list, "string").text = name
        return response

    def handle_GetParameterNames(self, element):
        path = element.findtext("ParameterPath") or ""
        next_level = (element.findtext("NextLevel") or "0") in {"1", "true", "True"}
        names = self.select_parameter_names(path, next_level)
        response = ET.Element(ET.QName(CWMP, "GetParameterNamesResponse"))
        param_list = ET.SubElement(response, "ParameterList")
        param_list.set(ET.QName(SOAP_ENC, "arrayType"), f"cwmp:ParameterInfoStruct[{len(names)}]")
        for name in names:
            info = ET.SubElement(param_list, "ParameterInfoStruct")
            ET.SubElement(info, "Name").text = name
            ET.SubElement(info, "Writable").text = "1" if self.parameters.is_writable(name.rstrip(".")) else "0"
        return response

    def select_parameter_names(self, path, next_level):
        all_names = self.parameters.parameter_names()
        if not path:
            return [name for name in all_names if name.count(".") <= 1 or name in {"Device.", "InternetGatewayDevice."}]
        if next_level:
            results = []
            for name in all_names:
                if name.startswith(path) and name != path:
                    suffix = name[len(path):]
                    if "." not in suffix.strip("."):
                        results.append(name)
            return sorted(set(results))
        return [name for name in all_names if name.startswith(path)]

    def handle_GetParameterValues(self, element):
        names = [item.text or "" for item in element.findall("./ParameterNames/string")]
        selected = []
        for requested in names:
            if requested.endswith("."):
                for name in self.parameters.parameter_names():
                    if not name.endswith(".") and name.startswith(requested):
                        selected.append(name)
            elif self.parameters.get_value(requested):
                selected.append(requested)
        selected = sorted(set(selected))
        response = ET.Element(ET.QName(CWMP, "GetParameterValuesResponse"))
        param_list = ET.SubElement(response, "ParameterList")
        param_list.set(ET.QName(SOAP_ENC, "arrayType"), f"cwmp:ParameterValueStruct[{len(selected)}]")
        for name in selected:
            value_type, value = self.parameters.get_value(name)
            item = ET.SubElement(param_list, "ParameterValueStruct")
            ET.SubElement(item, "Name").text = name
            value_elem = ET.SubElement(item, "Value")
            value_elem.set(ET.QName(XSI, "type"), f"xsd:{self.xsd_type(value_type)}")
            value_elem.text = self.serialize_value(value_type, value)
        return response

    def handle_SetParameterValues(self, element):
        for item in element.findall("./ParameterList/ParameterValueStruct"):
            name = item.findtext("Name") or ""
            value_elem = item.find("Value")
            current = self.parameters.get_value(name)
            if current is None:
                continue
            target_type = current[0]
            value = self.parse_value(target_type, value_elem.text if value_elem is not None else "")
            self.parameters.set_value(name, value)
        response = ET.Element(ET.QName(CWMP, "SetParameterValuesResponse"))
        ET.SubElement(response, "Status").text = "0"
        return response

    def handle_GetParameterAttributes(self, element):
        names = [item.text or "" for item in element.findall("./ParameterNames/string")]
        response = ET.Element(ET.QName(CWMP, "GetParameterAttributesResponse"))
        attr_list = ET.SubElement(response, "ParameterList")
        attr_list.set(ET.QName(SOAP_ENC, "arrayType"), f"cwmp:ParameterAttributeStruct[{len(names)}]")
        for name in names:
            item = ET.SubElement(attr_list, "ParameterAttributeStruct")
            ET.SubElement(item, "Name").text = name
            ET.SubElement(item, "Notification").text = "0"
            access_list = ET.SubElement(item, "AccessList")
            access_list.set(ET.QName(SOAP_ENC, "arrayType"), "xsd:string[0]")
        return response

    def handle_SetParameterAttributes(self, _element):
        return ET.Element(ET.QName(CWMP, "SetParameterAttributesResponse"))

    def handle_Download(self, element):
        url = element.findtext("URL") or ""
        command_key = element.findtext("CommandKey") or ""
        filename = pathlib.Path(urllib.parse.urlparse(url).path).name or "download.bin"
        target = pathlib.Path("/var/lib/cwmp-client/downloads") / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.opener.open(url, timeout=30) as response:
                target.write_bytes(response.read())
            self.state.data["last_download"] = str(target)
            self.state.save()
            fault_code = "0"
            fault_string = ""
        except Exception as exc:
            fault_code = "9010"
            fault_string = str(exc)
        response = ET.Element(ET.QName(CWMP, "DownloadResponse"))
        ET.SubElement(response, "Status").text = "0" if fault_code == "0" else "1"
        ET.SubElement(response, "StartTime").text = utc_now()
        ET.SubElement(response, "CompleteTime").text = utc_now()
        if fault_code != "0":
            print(f"[cwmp] download {command_key} failed: {fault_string}", flush=True)
        return response

    def handle_Reboot(self, _element):
        self.pending_boot = True
        response = ET.Element(ET.QName(CWMP, "RebootResponse"))
        return response

    def handle_FactoryReset(self, _element):
        self.state.data["parameter_values"] = {}
        self.state.data["software_version"] = os.environ.get("CWMP_SOFTWARE_VERSION", "lab-cwmp-client/1.0")
        self.state.data["first_boot"] = True
        self.state.save()
        response = ET.Element(ET.QName(CWMP, "FactoryResetResponse"))
        return response

    def next_events(self):
        if self.pending_events:
            events = self.pending_events[:]
            self.pending_events.clear()
            return events
        if self.state.data["first_boot"]:
            self.state.data["first_boot"] = False
            self.state.data["boot_count"] += 1
            self.state.save()
            return ["0 BOOTSTRAP", "1 BOOT"]
        if self.pending_boot:
            self.pending_boot = False
            self.state.data["boot_count"] += 1
            self.state.save()
            return ["1 BOOT"]
        return ["2 PERIODIC"]

    def run(self):
        self.start_connection_request_listener()
        self.inform_now.set()
        while not self.stop_event.is_set():
            interval = int(self.parameters.get_value("Device.ManagementServer.PeriodicInformInterval")[1] or 60)
            enabled = bool(self.parameters.get_value("Device.ManagementServer.PeriodicInformEnable")[1])
            if enabled:
                self.inform_now.wait(timeout=max(interval, 5))
            else:
                self.inform_now.wait(timeout=5)
            self.inform_now.clear()
            events = self.next_events()
            self.maybe_session(events)

    def start_connection_request_listener(self):
        client = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.handle_request()

            def do_POST(self):
                self.handle_request()

            def handle_request(self):
                expected_user = client.parameters.state.data["parameter_values"].get(
                    "Device.ManagementServer.ConnectionRequestUsername",
                    client.parameters.connection_request_username,
                )
                expected_pass = client.parameters.state.data["parameter_values"].get(
                    "Device.ManagementServer.ConnectionRequestPassword",
                    client.parameters.connection_request_password,
                )
                auth = self.headers.get("Authorization", "")
                allow_unauth = os.environ.get("CWMP_ALLOW_UNAUTH_CONNECTION_REQUEST", "true").lower() in (
                    "1",
                    "true",
                    "yes",
                )
                if expected_user and auth:
                    encoded = base64.b64encode(f"{expected_user}:{expected_pass}".encode()).decode()
                    if auth != f"Basic {encoded}":
                        self.send_response(401)
                        self.send_header("WWW-Authenticate", 'Basic realm="cwmp"')
                        self.end_headers()
                        return
                elif expected_user and not allow_unauth:
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", 'Basic realm="cwmp"')
                    self.end_headers()
                    return
                client.state.data["connection_request_count"] += 1
                client.state.save()
                client.pending_events.append("6 CONNECTION REQUEST")
                client.inform_now.set()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK")

            def log_message(self, *_args):
                return

        port = self.parameters.connection_request_port
        server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(f"[cwmp] connection request listener on {port}", flush=True)


if __name__ == "__main__":
    CWMPClient().run()
