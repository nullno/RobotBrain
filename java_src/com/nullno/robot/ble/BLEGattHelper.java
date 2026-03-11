package com.nullno.robot.ble;

import android.annotation.SuppressLint;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.content.Context;
import android.os.Build;

import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * BLE GATT 读写辅助类，供 Python (pyjnius) 调用。
 */
@SuppressLint("MissingPermission")
public class BLEGattHelper {

    private BluetoothGatt gatt;
    private volatile boolean connected = false;
    private volatile boolean servicesDiscovered = false;
    private volatile byte[] readValue = null;
    private volatile boolean writeSuccess = false;

    private CountDownLatch connectLatch;
    private CountDownLatch servicesLatch;
    private CountDownLatch readLatch;
    private CountDownLatch writeLatch;

    @SuppressWarnings("deprecation")
    private final BluetoothGattCallback gattCallback = new BluetoothGattCallback() {
        @Override
        public void onConnectionStateChange(BluetoothGatt g, int status, int newState) {
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                connected = true;
                g.discoverServices();
            } else {
                connected = false;
            }
            if (connectLatch != null) connectLatch.countDown();
        }

        @Override
        public void onServicesDiscovered(BluetoothGatt g, int status) {
            servicesDiscovered = (status == BluetoothGatt.GATT_SUCCESS);
            if (servicesLatch != null) servicesLatch.countDown();
        }

        @Override
        public void onCharacteristicRead(BluetoothGatt g,
                                         BluetoothGattCharacteristic c, int status) {
            if (status == BluetoothGatt.GATT_SUCCESS) {
                readValue = c.getValue();
            }
            if (readLatch != null) readLatch.countDown();
        }

        @Override
        public void onCharacteristicWrite(BluetoothGatt g,
                                          BluetoothGattCharacteristic c, int status) {
            writeSuccess = (status == BluetoothGatt.GATT_SUCCESS);
            if (writeLatch != null) writeLatch.countDown();
        }
    };

    @SuppressWarnings("deprecation")
    public boolean connect(Context context, String address, int timeoutSec) {
        BluetoothManager manager =
                (BluetoothManager) context.getSystemService(Context.BLUETOOTH_SERVICE);
        if (manager == null) return false;
        BluetoothDevice device = manager.getAdapter().getRemoteDevice(address);
        if (device == null) return false;

        connectLatch = new CountDownLatch(1);
        servicesLatch = new CountDownLatch(1);

        if (Build.VERSION.SDK_INT >= 23) {
            gatt = device.connectGatt(context, false, gattCallback,
                    BluetoothDevice.TRANSPORT_LE);
        } else {
            gatt = device.connectGatt(context, false, gattCallback);
        }

        try {
            if (!connectLatch.await(timeoutSec, TimeUnit.SECONDS)) return false;
            if (!connected) return false;
            if (!servicesLatch.await(timeoutSec, TimeUnit.SECONDS)) return false;
        } catch (InterruptedException e) {
            return false;
        }
        return connected && servicesDiscovered;
    }

    @SuppressWarnings("deprecation")
    public byte[] readCharacteristic(String serviceUuid, String charUuid,
                                     int timeoutSec) {
        if (gatt == null) return null;
        BluetoothGattService service = gatt.getService(UUID.fromString(serviceUuid));
        if (service == null) return null;
        BluetoothGattCharacteristic c =
                service.getCharacteristic(UUID.fromString(charUuid));
        if (c == null) return null;

        readLatch = new CountDownLatch(1);
        readValue = null;
        gatt.readCharacteristic(c);

        try {
            readLatch.await(timeoutSec, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            return null;
        }
        return readValue;
    }

    @SuppressWarnings("deprecation")
    public boolean writeCharacteristic(String serviceUuid, String charUuid,
                                       byte[] value, int timeoutSec) {
        if (gatt == null) return false;
        BluetoothGattService service = gatt.getService(UUID.fromString(serviceUuid));
        if (service == null) return false;
        BluetoothGattCharacteristic c =
                service.getCharacteristic(UUID.fromString(charUuid));
        if (c == null) return false;

        writeLatch = new CountDownLatch(1);
        writeSuccess = false;
        c.setValue(value);
        c.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
        gatt.writeCharacteristic(c);

        try {
            writeLatch.await(timeoutSec, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            return false;
        }
        return writeSuccess;
    }

    public void disconnect() {
        if (gatt != null) {
            try { gatt.disconnect(); } catch (Exception ignored) { }
            try { gatt.close(); } catch (Exception ignored) { }
            gatt = null;
        }
        connected = false;
        servicesDiscovered = false;
    }

    public boolean isConnected() {
        return connected;
    }
}
