import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/strings.dart';
import '../../core/theme.dart';

/// Driver sign-in.
///
/// Deliberately has no "create account" affordance: there is no public
/// registration anywhere in FleetBeat (Section 9). Saying so plainly beats
/// leaving drivers hunting for a link that does not exist.
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key, required this.api, required this.onSignedIn});

  final ApiClient api;
  final void Function(Map<String, dynamic> session) onSignedIn;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();

  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;

    setState(() {
      _submitting = true;
      _error = null;
    });

    try {
      final session = await widget.api.login(
        _emailController.text.trim(),
        _passwordController.text,
      );
      final role = (session['user'] as Map<String, dynamic>)['role'] as String?;
      if (role != 'driver') {
        // The API would allow this login, but this app only has driver
        // screens - sending them here would be a dead end.
        await widget.api.clearSession();
        setState(() {
          _error = Strings.notADriver;
          _submitting = false;
        });
        return;
      }
      widget.onSignedIn(session);
    } on ApiException catch (error) {
      setState(() {
        _error = error.message;
        _submitting = false;
      });
    } catch (_) {
      setState(() {
        _error = Strings.loginFailed;
        _submitting = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const _BrandHeader(),
                    const SizedBox(height: 32),
                    Text(
                      Strings.loginTitle,
                      style: Theme.of(context).textTheme.titleLarge?.copyWith(
                            color: Colors.white,
                            fontWeight: FontWeight.w600,
                          ),
                    ),
                    const SizedBox(height: 20),
                    TextFormField(
                      controller: _emailController,
                      keyboardType: TextInputType.emailAddress,
                      autocorrect: false,
                      decoration: const InputDecoration(
                        labelText: Strings.emailLabel,
                      ),
                      validator: (value) =>
                          (value == null || !value.contains('@'))
                              ? 'Enter your work email'
                              : null,
                    ),
                    const SizedBox(height: 14),
                    TextFormField(
                      controller: _passwordController,
                      obscureText: true,
                      decoration: const InputDecoration(
                        labelText: Strings.passwordLabel,
                      ),
                      validator: (value) => (value == null || value.isEmpty)
                          ? 'Enter your password'
                          : null,
                      onFieldSubmitted: (_) => _submit(),
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 14),
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: FleetBeatColors.danger.withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Text(
                          _error!,
                          style: const TextStyle(
                            color: FleetBeatColors.danger,
                            fontSize: 13,
                          ),
                        ),
                      ),
                    ],
                    const SizedBox(height: 20),
                    FilledButton(
                      onPressed: _submitting ? null : _submit,
                      child: Text(
                        _submitting ? Strings.signingIn : Strings.signIn,
                      ),
                    ),
                    const SizedBox(height: 24),
                    Text(
                      Strings.noSignup,
                      style: TextStyle(
                        fontSize: 12,
                        height: 1.5,
                        color: Colors.white.withValues(alpha: 0.45),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _BrandHeader extends StatelessWidget {
  const _BrandHeader();

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Container(
          width: 56,
          height: 56,
          decoration: BoxDecoration(
            color: FleetBeatColors.electricBlue,
            borderRadius: BorderRadius.circular(16),
          ),
          child: const Icon(Icons.monitor_heart_outlined,
              color: Colors.white, size: 30),
        ),
        const SizedBox(height: 14),
        const Text(
          Strings.appName,
          style: TextStyle(
            color: Colors.white,
            fontSize: 20,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          Strings.tagline,
          style: TextStyle(
            fontSize: 13,
            color: Colors.white.withValues(alpha: 0.5),
          ),
        ),
      ],
    );
  }
}
