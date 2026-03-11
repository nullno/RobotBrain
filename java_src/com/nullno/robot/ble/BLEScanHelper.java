package com.nullno.robot.ble;

import android.annotation.SuppressLint;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothManager;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanRecord;
import android.bluetooth.le.ScanResult;
import android.content.Context;

import java.util.ArrayList;
import java.util.List;

/**
 * BLE 扫描辅助类，供 Python (pyjnius) 调用。
 */
@SuppressLint("MissingPermission")
public class BLEScanHelper {

    private BluetoothLeScanner scanner;
    private final List<String> discoveredDevices = new ArrayList<>();
    private volatile boolean scanning = false;
    private volatile int scanError = -1;

    private final ScanCallback callback = new ScanCallback() {
        @Override
        public void onScanResult(int callbackType, ScanResult result) {
            BluetoothDevice device = result.getDevice();
            String name = device.getName();
            if (name == null) {
                ScanRecord record = result.getScanRecord();
                if (record != null) {
                    name = record.getDeviceName();
                }
            }
            if (name == null) name = "";
            String address = device.getAddress();
            String entry = name + "|" + address;
            synchronized (discoveredDevices) {
                if (!discoveredDevices.contains(entry)) {
                    discoveredDevices.add(entry);
                }
            }
        }

        @Override
        public void onScanFailed(int errorCode) {
            scanError = errorCode;
            scanning = false;
        }
    };

    public BLEScanHelper(Context context) {
        BluetoothManager manager =
                (BluetoothManager) context.getSystemService(Context.BLUETOOTH_SERVICE);
        if (manager != null) {
            BluetoothAdapter adapter = manager.getAdapter();
            if (adapter != null) {
                scanner = adapter.getBluetoothLeScanner();
            }
        }
    }

    public void startScan() {
        synchronized (discoveredDevices) {
            discoveredDevices.clear();
        }
        scanError = -1;
        scanning = true;
        if (scanner != null) {
            scanner.startScan(callback);
        } else {
            scanError = -2;
            scanning = false;
        }
    }

    public void stopScan() {
        scanning = false;
        if (scanner != null) {
            try {
                scanner.stopScan(callback);
            } catch (Exception ignored) {
            }
        }
    }

    public List<String> getDiscoveredDevices() {
        synchronized (discoveredDevices) {
            return new ArrayList<>(discoveredDevices);
        }
    }

    public boolean isScanning() {
        return scanning;
    }

    public int getScanError() {
        return scanError;
    }
}
