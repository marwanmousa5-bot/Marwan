import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// Error carrying the API's own machine-readable code.
class ApiException implements Exception {
  ApiException(this.statusCode, this.code, this.message);

  final int statusCode;
  final String code;
  final String message;

  @override
  String toString() => message;
}

/// Thin client over the same FastAPI backend the web dashboard uses.
///
/// There is no registration call here and there never will be: driver
/// accounts are created by an Org Admin or by FleetBeat staff (Section 9).
class ApiClient {
  ApiClient({String? baseUrl, http.Client? httpClient})
      : baseUrl = baseUrl ??
            const String.fromEnvironment(
              'FLEETBEAT_API_BASE_URL',
              defaultValue: 'http://10.0.2.2:8000/api/v1',
            ),
        _http = httpClient ?? http.Client();

  static const _accessKey = 'fleetbeat.access_token';
  static const _refreshKey = 'fleetbeat.refresh_token';

  final String baseUrl;
  final http.Client _http;

  String? _accessToken;
  String? _refreshToken;

  bool get hasSession => _accessToken != null;

  Future<void> restoreSession() async {
    final prefs = await SharedPreferences.getInstance();
    _accessToken = prefs.getString(_accessKey);
    _refreshToken = prefs.getString(_refreshKey);
  }

  Future<void> _persistTokens(Map<String, dynamic> tokens) async {
    _accessToken = tokens['access_token'] as String?;
    _refreshToken = tokens['refresh_token'] as String?;
    final prefs = await SharedPreferences.getInstance();
    if (_accessToken != null) await prefs.setString(_accessKey, _accessToken!);
    if (_refreshToken != null) {
      await prefs.setString(_refreshKey, _refreshToken!);
    }
  }

  Future<void> clearSession() async {
    _accessToken = null;
    _refreshToken = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_accessKey);
    await prefs.remove(_refreshKey);
  }

  Map<String, String> _headers({bool anonymous = false}) {
    final headers = {'Content-Type': 'application/json'};
    if (!anonymous && _accessToken != null) {
      headers['Authorization'] = 'Bearer $_accessToken';
    }
    return headers;
  }

  ApiException _toException(http.Response response) {
    var code = 'error';
    var message = 'Request failed (${response.statusCode})';
    try {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      if (body['code'] is String) code = body['code'] as String;
      if (body['detail'] is String) message = body['detail'] as String;
    } catch (_) {
      // Non-JSON body - keep the default message.
    }
    return ApiException(response.statusCode, code, message);
  }

  Future<Map<String, dynamic>> login(String email, String password) async {
    final response = await _http.post(
      Uri.parse('$baseUrl/auth/login'),
      headers: _headers(anonymous: true),
      body: jsonEncode({'email': email, 'password': password}),
    );
    if (response.statusCode != 200) throw _toException(response);

    final body = jsonDecode(response.body) as Map<String, dynamic>;
    await _persistTokens(body['tokens'] as Map<String, dynamic>);
    return body;
  }

  Future<bool> _refresh() async {
    if (_refreshToken == null) return false;
    final response = await _http.post(
      Uri.parse('$baseUrl/auth/refresh'),
      headers: _headers(anonymous: true),
      body: jsonEncode({'refresh_token': _refreshToken}),
    );
    if (response.statusCode != 200) {
      await clearSession();
      return false;
    }
    await _persistTokens(jsonDecode(response.body) as Map<String, dynamic>);
    return true;
  }

  Future<dynamic> get(String path, {bool retried = false}) async {
    final response = await _http.get(
      Uri.parse('$baseUrl$path'),
      headers: _headers(),
    );
    if (response.statusCode == 401 && !retried && await _refresh()) {
      return get(path, retried: true);
    }
    if (response.statusCode >= 400) throw _toException(response);
    return jsonDecode(response.body);
  }

  Future<void> logout() async {
    if (_refreshToken != null) {
      try {
        await _http.post(
          Uri.parse('$baseUrl/auth/logout'),
          headers: _headers(),
          body: jsonEncode({'refresh_token': _refreshToken}),
        );
      } catch (_) {
        // Clearing local state matters more than the server round-trip.
      }
    }
    await clearSession();
  }
}
